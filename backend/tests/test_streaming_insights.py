"""Streaming pipeline events (real, ordered, timed) and the read-only insight endpoints that feed the UI's charts."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api import dashboard, insights
from app.graph import builder, nodes
from app.historical import runtime
from app.main import app
from app.services import drivers_service, fusion_service
from tests import test_drivers, test_fusion

client = TestClient(app)
ACCEPTANCE = "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?"


def stream(q):
    r = client.post("/api/query/stream", json={"query": q})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


# ------------------------------------------------------------------ streaming
def test_stream_reports_the_real_plan_and_every_step_in_order():
    ev = stream(ACCEPTANCE)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "start" and kinds[1] == "plan" and kinds[-1] == "result"
    plan = ev[1]
    assert plan["steps"] == plan["parsed"]["analysis_steps"] and plan["duration_ms"] >= 0 and plan["parsed"]["intent"] == "event_impact"
    started = [e["step"] for e in ev if e["type"] == "step_start"]
    done = [e["step"] for e in ev if e["type"] == "step_done"]
    assert started == done == [s for s in plan["steps"] if s in nodes.IMPLEMENTED]          # each step starts, then finishes, in plan order
    for i, e in enumerate(ev):                                                            # a step_start always directly precedes its step_done
        if e["type"] == "step_done":
            assert ev[i - 1]["type"] == "step_start" and ev[i - 1]["step"] == e["step"]
            assert isinstance(e["duration_ms"], int) and e["duration_ms"] >= 0 and e["status"] in ("completed", "failed")
    res = ev[-1]
    assert res["total_ms"] >= sum(e["duration_ms"] for e in ev if e["type"] in ("plan", "step_done")) - 5
    assert [s["step"] for s in res["data"]["steps"]] == [s for s in nodes.STEP_ORDER if s in done]


def test_stream_result_matches_the_non_streaming_endpoint():
    final = stream(ACCEPTANCE)[-1]["data"]
    plain = client.post("/api/query", json={"query": ACCEPTANCE}).json()
    for body in (final, plain):
        for k in ("weather", "news", "market", "historical", "exposure", "scenario", "risk", "drivers", "fusion", "hedging"):
            body[k] = bool(body.get(k))                                           # compare structure; timestamps differ per call
    assert final["steps"] == plain["steps"] and final["parsed"] == plain["parsed"]
    assert {k: final[k] for k in ("weather", "historical", "risk", "hedging")} == {k: plain[k] for k in ("weather", "historical", "risk", "hedging")}


def test_stream_only_announces_steps_the_question_needs():
    ev = stream("Explain why my portfolio risk increased.")
    assert [e["step"] for e in ev if e["type"] == "step_start"] == ["news", "market", "exposure", "risk", "drivers"]
    assert "weather" not in {e.get("step") for e in ev}


def test_a_crashing_agent_is_reported_as_failed_and_the_stream_continues(monkeypatch):
    def crash(parsed):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(builder._AGENT_NODES, "news", nodes._agent_node("news", crash))
    builder.get_graph.cache_clear()
    try:
        ev = stream(ACCEPTANCE)
    finally:
        builder.get_graph.cache_clear()
    news = next(e for e in ev if e["type"] == "step_done" and e["step"] == "news")
    assert news["status"] == "failed" and "kaboom" not in json.dumps(ev)
    assert ev[-1]["type"] == "result" and next(e for e in ev if e.get("step") == "market" and e["type"] == "step_done")["status"] == "completed"


def test_stream_error_event_carries_a_safe_message(monkeypatch):
    monkeypatch.setattr(builder, "get_graph", lambda: (_ for _ in ()).throw(RuntimeError("secret internals")))
    ev = stream(ACCEPTANCE)
    assert ev[-1]["type"] == "error" and "secret" not in ev[-1]["message"] and ev[-1]["message"]


def test_stream_validates_input_like_the_plain_endpoint():
    for bad in ("", "ab", "x" * 501):
        assert client.post("/api/query/stream", json={"query": bad}).status_code == 422


# ------------------------------------------------------------------ data the charts need
@pytest.fixture
def db(monkeypatch):
    insights._cache.clear()
    factory = test_drivers.seed(turbulent_end=True)
    for mod in (insights, drivers_service):
        monkeypatch.setattr(mod, "get_sessionmaker", lambda f=factory: f)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    yield factory
    insights._cache.clear()


def test_risk_drivers_endpoint_includes_the_rolling_volatility_series(db):
    d = client.get("/api/insights/risk-drivers").json()
    assert d["status"] == "ok" and 100 <= len(d["rolling_volatility"]) <= 252
    assert d["rolling_volatility"][-1]["date"] == d["prices_as_of"]
    assert d["rolling_volatility"][-1]["vol_pct"] == pytest.approx(d["risk_change"]["recent_vol_pct"])     # the last point IS the headline number
    dates = [p["date"] for p in d["rolling_volatility"]]
    assert dates == sorted(dates)


def test_prices_endpoint_is_rebased_validated_and_skips_unknown_symbols(db):
    out = client.get("/api/insights/prices", params={"symbols": "XOM,UNG,NOPE", "days": 100}).json()
    assert [s["symbol"] for s in out["series"]] == ["XOM", "UNG"]
    for s in out["series"]:
        assert len(s["points"]) == 100 and s["points"][0][1] == 100.0
        assert s["change_pct"] == pytest.approx(s["points"][-1][1] - 100, abs=0.01)
    assert client.get("/api/insights/prices", params={"symbols": "<script>"}).status_code == 422
    assert client.get("/api/insights/prices", params={"days": 5}).status_code == 422


def test_data_coverage_reports_what_is_stored(db):
    c = client.get("/api/insights/data-coverage").json()
    assert c["market"]["series"] == 3 and c["market"]["observations"] > 300 and c["storms"]["count"] == 0
    assert {s["series_key"] for s in c["market"]["detail"]} == {"yahoo:XOM", "yahoo:CVX", "yahoo:UNG"}


def test_insight_endpoints_return_503_without_a_database(monkeypatch):
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    insights._cache.clear()
    assert client.get("/api/insights/prices").status_code == 503 and client.get("/api/insights/data-coverage").status_code == 503
    assert client.get("/api/insights/risk-drivers").json()["status"] == "unavailable"          # reported, never faked


# ------------------------------------------------------------------ the dots behind the fusion distribution
def test_fusion_exposes_one_dot_per_storm_that_matches_the_distribution(monkeypatch):
    monkeypatch.setattr(fusion_service, "get_sessionmaker", lambda f=test_fusion.seed(cars={"XOM": 2.0, "CVX": 2.0, "UNG": 2.0}): f)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    out = fusion_service.run_fusion(test_fusion.Q)
    dots = out.portfolio.per_storm
    assert len(dots) == out.portfolio.all_analogs.n == 12 and [d.year for d in dots] == sorted(d.year for d in dots)
    assert sum(d.independent for d in dots) == out.portfolio.independent_only.n == 6
    assert sorted(d.value_pct for d in dots)[len(dots) // 2 - 1] <= out.portfolio.all_analogs.median <= sorted(d.value_pct for d in dots)[len(dots) // 2]
    assert all(d.label.endswith(str(d.year)) for d in dots)


def test_dashboard_summary_carries_the_storm_dots(monkeypatch):
    dashboard._cache.clear()
    monkeypatch.setattr(drivers_service, "get_sessionmaker", lambda f=test_drivers.seed(): f)
    monkeypatch.setattr(fusion_service, "get_sessionmaker", lambda f=test_fusion.seed(cars={"XOM": 1.0, "CVX": 1.0, "UNG": 1.0}): f)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    body = client.get("/api/dashboard/summary").json()
    assert len(body["hurricane_impact"]["storms"]) == 12 and {"label", "year", "value_pct", "independent"} <= set(body["hurricane_impact"]["storms"][0])
    dashboard._cache.clear()
