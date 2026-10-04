"""Phase 8: LangGraph pipeline (POST /api/query). Agents/LLM/providers are faked - no network."""
import pytest
from fastapi.testclient import TestClient

from app.agents import query_understanding as qu
from app.config import settings
from app.graph import builder, nodes
from app.main import app
from app.services import llm_client
from app.services.providers import nhc
from app.services.providers.base import ProviderError

client = TestClient(app)
ACCEPTANCE = "How will a Category 4 hurricane in the Gulf of Mexico affect my current energy holdings?"
PORTFOLIO_Q = "What are the biggest risks to my portfolio today?"


def ask(q: str) -> dict:
    r = client.post("/api/query", json={"query": q})
    assert r.status_code == 200, r.text
    return r.json()


def statuses(body: dict) -> dict[str, str]:
    return {s["step"]: s["status"] for s in body["steps"]}


@pytest.fixture
def calls(monkeypatch):
    """Replace the three agent entry points with spies and record call order."""
    seen: list[str] = []
    b = builder

    def spy(step):
        def run(parsed):
            seen.append(step)
            return {"weather": nodes.run_weather_agent, "news": nodes.run_news_agent,
                    "market": nodes.run_market_agent}[step](parsed)
        return run

    monkeypatch.setitem(b._AGENT_NODES, "weather", nodes._agent_node("weather", spy("weather")))
    monkeypatch.setitem(b._AGENT_NODES, "news", nodes._agent_node("news", spy("news")))
    monkeypatch.setitem(b._AGENT_NODES, "market", nodes._agent_node("market", spy("market")))
    b.get_graph.cache_clear()
    yield seen
    b.get_graph.cache_clear()


# ============================================================ 7. correct agents are invoked
def test_event_impact_runs_weather_news_market_in_order(calls):
    body = ask(ACCEPTANCE)
    assert calls == ["weather", "news", "market"]
    assert body["orchestrator"] == "langgraph"
    assert body["weather"]["status"] == "matched" and body["news"]["status"] == "ok"
    assert [a["symbol"] for a in body["market"]["assets"]] == ["XOM", "CVX", "UNG"]
    st = statuses(body)
    assert [st[s] for s in ("weather", "news", "market")] == ["completed"] * 3
    # every pipeline step now has an agent (hedging was the last one); nothing is reported as not implemented
    assert all(st[s] == "completed" for s in ("historical", "exposure", "scenario", "risk", "fusion", "hedging"))
    assert "not_implemented" not in st.values()
    # steps come back in canonical pipeline order
    assert [s["step"] for s in body["steps"]] == [s for s in nodes.STEP_ORDER if s != "drivers"]   # drivers is for risk questions


def test_portfolio_risk_skips_weather(calls):
    body = ask(PORTFOLIO_Q)
    assert calls == ["news", "market"]  # weather was not requested -> never called
    assert body["weather"] is None and body["news"] and body["market"]
    assert statuses(body) == {"news": "completed", "market": "completed",
                              "exposure": "completed", "risk": "completed", "drivers": "completed"}


def test_question_needing_no_implemented_agent_calls_none(calls):
    body = ask("Which assets are most exposed?")
    assert calls == []
    assert body["weather"] is None and body["news"] is None and body["market"] is None
    assert statuses(body) == {"exposure": "completed"}


def test_unrecognised_question_runs_nothing(calls):
    body = ask("What is the capital of France?")
    assert calls == [] and body["steps"] == [] and body["parsed"]["intent"] == "other"


def test_steps_without_an_agent_still_carry_no_fake_results():
    """The safety net: a requested step that has no agent is reported not_implemented and returns no payload."""
    out = nodes.finalize_node({"pending": ["hedging"]})        # whatever is still pending when routing ends has no agent
    assert [(r.step, r.status) for r in out["runs"]] == [("hedging", "not_implemented")] and out["pending"] == []
    assert "hedging" in ask(ACCEPTANCE)           # implemented now: it has a real payload field


def test_a_crashing_agent_does_not_break_the_query(monkeypatch):
    def crash(parsed):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(builder._AGENT_NODES, "news", nodes._agent_node("news", crash))
    builder.get_graph.cache_clear()
    try:
        body = ask(ACCEPTANCE)
    finally:
        builder.get_graph.cache_clear()
    st = statuses(body)
    assert st["news"] == "failed" and body["news"] is None
    assert st["weather"] == "completed" and st["market"] == "completed" and body["market"]
    assert "kaboom" not in str(body)


def test_agent_level_error_is_reported_as_failed_step(monkeypatch):
    from app.services import news_service
    monkeypatch.setattr(news_service, "get_news", lambda q=None: (_ for _ in ()).throw(RuntimeError("x")))
    body = ask(ACCEPTANCE)
    assert statuses(body)["news"] == "failed" and body["news"]["status"] == "error"
    assert body["market"]["status"] == "ok"  # others unaffected


def test_graph_is_compiled_once():
    assert builder.get_graph() is builder.get_graph()


def test_query_endpoint_validates_input():
    for bad in ("", "ab", "x" * 501):
        assert client.post("/api/query", json={"query": bad}).status_code == 422


# ============================================================ 8. Weather Agent unchanged
def test_weather_agent_output_is_identical_inside_the_pipeline():
    standalone = client.post("/api/weather/analyze", json={"query": ACCEPTANCE}).json()["weather"]
    in_pipeline = ask(ACCEPTANCE)["weather"]
    for w in (standalone, in_pipeline):
        w["meta"].pop("as_of")  # wall-clock time of each call - the only field allowed to differ
    assert in_pipeline == standalone
    assert in_pipeline["meta"]["source"] == "demo" and in_pipeline["primary_event"]["category"] == 4
    assert client.get("/api/weather").json()["events"][0]["category"] == 4


def test_unsupported_event_still_handled_by_weather_agent():
    body = ask("How would an earthquake in Japan hurt my tech holdings?")
    assert body["weather"]["status"] == "unsupported_event" and body["weather"]["meta"] is None
    assert body["parsed"]["supported"] is False and body["parsed"]["warnings"]


# ============================================================ 9. LLM query understanding unchanged
@pytest.fixture
def llm_on(monkeypatch):
    """LLM configured, DEMO_MODE off. Weather provider faked (no network); market/news keys are
    empty, so they use labeled demo data without any call."""
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [])


def test_pipeline_uses_the_llm_parse_when_available(llm_on, monkeypatch):
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: {
        "intent": "event_impact", "event_type": "hurricane", "event_category": 4,
        "region": "Gulf of Mexico", "sectors": ["Energy"], "assets": [], "uses_portfolio": True,
        "analysis_steps": ["market"], "confidence": 0.95})
    monkeypatch.setattr(llm_client, "active_model", lambda: "gemini-test")
    body = ask(ACCEPTANCE)
    assert body["parsed"]["parser"] == "llm" and body["parsed"]["llm_model"] == "gemini-test"
    assert body["parse_notice"] is None
    assert statuses(body) == {"market": "completed"}  # only what the LLM asked for runs
    assert body["market"]["meta"]["source"] == "demo" and "no API key" in body["market"]["meta"]["notice"]


def test_pipeline_keeps_rule_based_fallback_when_llm_fails(llm_on, monkeypatch):
    def fail(s, u):
        raise ProviderError("HTTP 503")

    monkeypatch.setattr(llm_client, "complete_json", fail)
    body = ask(ACCEPTANCE)
    assert body["parsed"]["parser"] == "rules" and "rule-based parser" in body["parse_notice"]
    assert statuses(body)["weather"] == "completed" and statuses(body)["news"] == "completed"
    assert body["weather"]["meta"]["source"] == "live"  # (faked) live NHC feed, empty -> hypothetical


def test_parse_endpoint_is_unchanged():
    r = client.post("/api/query/parse", json={"query": ACCEPTANCE}).json()
    assert r["parsed"]["parser"] == "rules" and "Demo mode is ON" in r["notice"]
    assert qu.understand_query(ACCEPTANCE).parsed.event_category == 4
