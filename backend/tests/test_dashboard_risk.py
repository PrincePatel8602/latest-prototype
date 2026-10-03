"""Real returns feeding the Phase 10 risk engine, and the dashboard summary endpoint."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.quant_agent import run_risk_agent
from app.api import dashboard
from app.historical import runtime
from app.historical.models import HistoricalBase
from app.main import app
from app.quant.risk_engine import risk, scenario_hurricane
from app.schemas.query import ParsedQuery
from app.services import drivers_service, fusion_service, portfolio_service, risk_data
from tests import test_drivers, test_fusion

Q = ParsedQuery(intent="portfolio_risk", confidence=1.0, parser="rules")
client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_dashboard_cache():
    dashboard._cache.clear()
    yield
    dashboard._cache.clear()


def wire_risk_data(monkeypatch, factory):
    monkeypatch.setattr(risk_data, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)


# ------------------------------------------------------------------ Phase 10 risk engine gets real returns
def test_real_returns_replace_the_assumed_volatility(monkeypatch):
    wire_risk_data(monkeypatch, test_drivers.seed())
    r = run_risk_agent(Q, scenario_hurricane(portfolio_service.get_portfolio()))
    assert r.volatility_method == "historical_return_series" and r.historical_var_method == "historical_95_percentile"
    assert r.historical_var_95_pct is not None and r.historical_var_95_pct > 0 and r.meta.source == "live"
    assert any("'Other assets' (35%" in x for x in r.limitations)
    assert not any("assumption-based" in x for x in r.limitations)
    assert r.scenario_change_pct == pytest.approx(3.7)                       # the scenario assumptions are untouched


def test_without_stored_history_the_labelled_assumption_fallback_remains(monkeypatch):
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    r = run_risk_agent(Q, None)
    assert r.volatility_method == "assumption_based_weighted_volatility" and r.historical_var_95_pct is None and r.meta.source == "demo"
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    wire_risk_data(monkeypatch, sessionmaker(bind=engine))                    # DB reachable but empty
    assert risk_data.real_returns(portfolio_service.get_portfolio()) is None


def test_phase10_engine_itself_is_unchanged_when_no_returns_are_passed():
    p = portfolio_service.get_portfolio()
    r = risk(p, scenario_hurricane(p))
    assert r.volatility_method == "assumption_based_weighted_volatility" and r.historical_var_method == "not_available"


# ------------------------------------------------------------------ dashboard tiles
def test_dashboard_summary_returns_both_tiles_and_caches(monkeypatch):
    monkeypatch.setattr(drivers_service, "get_sessionmaker", lambda: test_drivers.seed(turbulent_end=True))
    monkeypatch.setattr(fusion_service, "get_sessionmaker", lambda: test_fusion.seed(cars={"XOM": 3.0, "CVX": 3.0, "UNG": 3.0}))
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    body = client.get("/api/dashboard/summary").json()
    r, h = body["risk"], body["hurricane_impact"]
    assert r["status"] == "ok" and r["classification"] == "elevated" and r["top_risk_symbol"] == "UNG" and r["covered_weight_pct"] == 65.0
    assert h["status"] == "ok" and h["n_storms"] == 12 and h["grade"] == "indicative" and h["p10_pct"] < h["median_pct"] < h["p90_pct"]
    assert h["reference_event"] == "Category 4 Gulf hurricane"
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)             # second call must come from the cache
    assert client.get("/api/dashboard/summary").json() == body


def test_dashboard_summary_reports_unavailable_instead_of_faking_and_does_not_cache_it(monkeypatch):
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    body = client.get("/api/dashboard/summary").json()
    assert body["risk"]["status"] == "unavailable" and body["hurricane_impact"]["status"] == "unavailable"
    assert body["risk"]["note"] and "recent_vol_pct" not in body["risk"] and "median_pct" not in body["hurricane_impact"]
    assert dashboard._cache.get("summary") is None
