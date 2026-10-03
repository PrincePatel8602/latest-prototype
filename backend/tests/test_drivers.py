"""Risk-driver tests: statistics with known answers, the service on seeded prices, and question routing."""
import random
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.analytics.models  # noqa: F401
import app.historical.market.models  # noqa: F401
import app.historical.physical.models  # noqa: F401
from app.analytics import drivers as dv
from app.historical import runtime
from app.historical.market.models import MarketObservation, MarketSeries
from app.historical.models import HistoricalBase
from app.schemas.query import ParsedQuery
from app.services import drivers_service


def make_prices(vol_by_segment, n, seed=1, start=date(2023, 1, 2), p0=100.0):
    """Business-day prices whose daily volatility changes by segment: [(until_index, daily_vol), ...]."""
    rng = random.Random(seed)
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    px, p = {}, p0
    for i, day in enumerate(dates):
        vol = next(v for until, v in vol_by_segment if i < until)
        p *= 1 + rng.gauss(0, vol)
        px[day] = p
    return px


# ------------------------------------------------------------------ pure statistics
def test_variance_shares_sum_to_100_and_identify_the_riskier_holding():
    calm, wild = make_prices([(400, 0.005)], 400, seed=1), make_prices([(400, 0.03)], 400, seed=2)
    dates, rets = dv.aligned_returns({"CALM": calm, "WILD": wild})
    shares = dv.variance_shares(rets, {"CALM": 0.5, "WILD": 0.5}, 250)
    assert sum(shares.values()) == pytest.approx(100.0) and shares["WILD"] > 90


def test_variance_share_of_a_single_holding_is_100():
    px = make_prices([(300, 0.01)], 300)
    _, rets = dv.aligned_returns({"A": px})
    assert dv.variance_shares(rets, {"A": 0.4}, 100)["A"] == pytest.approx(100.0)


def test_calm_then_turbulent_is_flagged_elevated_and_calm_stays_typical_or_subdued():
    turbulent = make_prices([(380, 0.006), (400, 0.04)], 400, seed=3)     # last 20 days far more volatile
    r = dv.analyse({"A": turbulent}, {"A": 0.5})
    assert r["classification"] == "elevated" and r["history_percentile"] >= 80 and r["vol_ratio"] > 1.5
    assert r["recent_vol_pct"] > r["year_vol_pct"]
    quiet = make_prices([(380, 0.02), (400, 0.003)], 400, seed=4)         # last 20 days far calmer
    q = dv.analyse({"A": quiet}, {"A": 0.5})
    assert q["classification"] == "subdued" and q["vol_ratio"] < 0.6


def test_volatility_scales_with_weight_and_top_risk_symbol_is_the_wild_one():
    a, b = make_prices([(400, 0.005)], 400, seed=5), make_prices([(400, 0.03)], 400, seed=6)
    r = dv.analyse({"A": a, "B": b}, {"A": 0.3, "B": 0.3})
    assert r["top_risk_symbol"] == "B" and {h["symbol"] for h in r["holdings"]} == {"A", "B"}
    assert sum(h["risk_share_recent_pct"] for h in r["holdings"]) == pytest.approx(100.0)


def test_too_little_history_returns_none():
    assert dv.analyse({"A": make_prices([(60, 0.01)], 60)}, {"A": 0.5}) is None
    assert dv.analyse({"A": make_prices([(300, 0.01)], 300)}, {"A": 0.5, "B": 0.5}) is None


def test_percentile_rank_and_classify():
    assert dv.percentile_rank([1, 2, 3, 4], 3) == 75.0 and dv.classify(85) == "elevated" and dv.classify(10) == "subdued" and dv.classify(50) == "typical"
    assert dv.compound([0.1, 0.1]) == pytest.approx(0.21)


# ------------------------------------------------------------------ service
def seed(turbulent_end=False, last_date_offset=0):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    end = now.date() - timedelta(days=last_date_offset)
    start = end - timedelta(days=600)
    with factory() as s:
        for sym, seed_ in (("XOM", 1), ("CVX", 2), ("UNG", 3)):
            s.add(MarketSeries(series_key=f"yahoo:{sym}", source="yahoo", source_series_id=sym, name=sym, category="equity", unit="USD",
                               frequency="daily", source_url="u", raw_file_sha256="a" * 64, fetched_at=now, n_observations=1))
        s.flush()
        for sym, seed_ in (("XOM", 1), ("CVX", 2), ("UNG", 3)):
            segs = [(380, 0.008), (10_000, 0.05 if turbulent_end and sym == "UNG" else 0.008)]
            px = make_prices(segs, 430, seed=seed_, start=start)
            dates = sorted(px)
            shift = end - dates[-1]
            s.bulk_insert_mappings(MarketObservation, [{"series_key": f"yahoo:{sym}", "obs_date": d + shift, "value": v} for d, v in px.items()])
        s.commit()
    return factory


@pytest.fixture
def wired(monkeypatch):
    def wire(factory):
        monkeypatch.setattr(drivers_service, "get_sessionmaker", lambda: factory)
        monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    return wire


Q = ParsedQuery(intent="explain_risk", confidence=1.0, parser="rules")


def test_service_says_risk_rose_when_recent_volatility_is_unusual(wired):
    wired(seed(turbulent_end=True))
    out = drivers_service.run_drivers(Q)
    assert out.status == "ok" and out.risk_change.classification == "elevated" and out.holdings[0].symbol == "UNG"
    assert "HAS risen" in out.conclusion and "UNG contributes the most" in out.conclusion
    assert out.covered_weight_pct == 65.0 and out.uncovered_weight_pct == 35.0 and not out.prices_stale
    assert out.concentration["largest_position"] == "XOM"            # the 'Other assets' bucket is not a position
    assert any("Phase 10 risk score" in x for x in out.limitations)


def test_service_says_no_rise_when_nothing_unusual_happened(wired):
    wired(seed(turbulent_end=False))
    out = drivers_service.run_drivers(Q)
    assert out.status == "ok" and out.risk_change.classification != "elevated" and "HAS risen" not in out.conclusion


def test_stale_prices_are_flagged(wired):
    wired(seed(last_date_offset=30))
    out = drivers_service.run_drivers(Q)
    assert out.prices_stale and "import_market.py" in out.conclusion


def test_unavailable_and_insufficient_paths(monkeypatch, wired):
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    assert drivers_service.run_drivers(Q).status == "unavailable"
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    wired(sessionmaker(bind=engine))
    out = drivers_service.run_drivers(Q)
    assert out.status == "insufficient_data" and out.risk_change is None and out.holdings == []


# ------------------------------------------------------------------ routing: risk questions always get exposure + risk + drivers
def test_risk_questions_route_to_drivers_even_when_the_llm_under_plans(monkeypatch):
    from app.agents import query_understanding as qu
    from app.config import settings
    from app.services import llm_client
    monkeypatch.setattr(settings, "demo_mode", False)      # LLM parsing is skipped in demo mode
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: {
        "intent": "explain_risk", "event_type": "none", "sectors": [], "assets": [], "uses_portfolio": True,
        "analysis_steps": ["risk"], "confidence": 1.0})
    p = qu.understand_query("Explain why my portfolio risk increased.").parsed
    assert p.parser == "llm" and p.analysis_steps == ["exposure", "risk", "drivers"]
    monkeypatch.setattr(settings, "llm_api_key", "")
    rules = qu.understand_query("Explain why my portfolio risk increased.").parsed
    assert rules.intent == "explain_risk" and rules.analysis_steps == ["news", "market", "exposure", "risk", "drivers"]


def test_event_questions_do_not_get_the_drivers_step():
    from app.agents.query_understanding import default_steps
    assert "drivers" not in default_steps("event_impact", "hurricane") and "fusion" in default_steps("event_impact", "hurricane")
