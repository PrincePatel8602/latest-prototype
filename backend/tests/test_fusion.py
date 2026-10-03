"""Evidence-fusion tests: statistics with known answers, then the service on a seeded database."""
import random
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.analytics.models  # noqa: F401
import app.historical.market.models  # noqa: F401
import app.historical.physical.models  # noqa: F401
from app.analytics import fusion as fx
from app.analytics.models import EventStudyResult
from app.historical import runtime
from app.historical.market.models import MarketObservation, MarketSeries
from app.historical.models import HistoricalBase, HistoricalStorm
from app.historical.physical.models import BseeStormShutin
from app.schemas.query import ParsedQuery
from app.services import fusion_service, portfolio_service


# ------------------------------------------------------------------ pure statistics
def test_percentile_matches_hand_values():
    v = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert fx.percentile(v, 0.5) == 3.0 and fx.percentile(v, 0.0) == 1.0 and fx.percentile(v, 1.0) == 5.0
    assert fx.percentile(v, 0.25) == 2.0 and fx.percentile([0.0, 10.0], 0.5) == 5.0


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    a, b = fx.bootstrap_mean_ci(vals), fx.bootstrap_mean_ci(vals)
    assert a == b and a[0] < 4.5 < a[1]
    assert fx.bootstrap_mean_ci([2.0] * 6) == (2.0, 2.0)


def test_grade_rules():
    assert fx.grade(4, (1, 2)) == "insufficient_data" and fx.grade(20, None) == "insufficient_data"
    assert fx.grade(20, (-1, 1)) == "not_distinguishable_from_zero"
    assert fx.grade(7, (0.5, 2)) == "weak_signal" and fx.grade(12, (0.5, 2)) == "indicative"
    assert fx.grade(12, (-2, -0.5)) == "indicative"


def test_summarize_clear_positive_effect_and_pure_noise():
    pos = fx.summarize([2.0 + 0.1 * i for i in range(15)])
    assert pos["grade"] == "indicative" and pos["median"] == pytest.approx(2.7) and pos["share_positive"] == 1.0
    rng = random.Random(3)
    noise = fx.summarize([rng.gauss(0, 2) for _ in range(30)])
    assert noise["grade"] == "not_distinguishable_from_zero"
    assert fx.summarize([1.0, 2.0])["grade"] == "insufficient_data" and fx.summarize([])["n"] == 0


def test_portfolio_series_uses_only_the_joint_sample_and_real_weights():
    per = {"s1": {"A": 2.0, "B": -1.0}, "s2": {"A": 4.0}, "s3": {"A": 1.0, "B": 3.0}}
    out = fx.portfolio_series(per, {"A": 0.5, "B": 0.2})
    assert set(out) == {"s1", "s3"} and out["s1"] == pytest.approx(0.5 * 2 + 0.2 * -1) and out["s3"] == pytest.approx(1.1)


def test_vs_range():
    assert fx.vs_range(5, -3, 4) == "above_historical_range" and fx.vs_range(-4, -3, 4) == "below_historical_range"
    assert fx.vs_range(0, -3, 4) == "within_historical_range" and fx.vs_range(1, None, None) == "no_history"


def test_sleeve_risk_known_series_and_insufficient_history():
    d0 = date(2020, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(101)]
    rng = random.Random(5)
    px, p = {}, 100.0
    for d in dates:
        px[d] = p
        p *= 1 + rng.gauss(0, 0.01)
    r = fx.sleeve_risk({"X": px}, {"X": 0.5})
    assert r["days"] == 100 and 0.3 < r["daily_std_pct"] < 0.8              # 0.5 * ~1% daily, in percent
    assert r["annualised_volatility_pct"] == pytest.approx(r["daily_std_pct"] * 252 ** 0.5)
    assert r["var95_1d_pct"] > 0 and r["worst_day_pct"] < 0
    assert fx.sleeve_risk({"X": {d: px[d] for d in dates[:30]}}, {"X": 0.5}) is None
    assert fx.sleeve_risk({"X": px}, {"X": 0.5, "Y": 0.5}) is None            # a weighted symbol with no prices


# ------------------------------------------------------------------ service on a seeded database
def seed(n_storms=12, cars=None, overlap_every=2, bsee=True):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    rng = random.Random(11)
    with factory() as s:
        for sym in ("XOM", "CVX", "UNG"):
            s.add(MarketSeries(series_key=f"yahoo:{sym}", source="yahoo", source_series_id=sym, name=sym, category="equity", unit="USD",
                               frequency="daily", source_url="u", raw_file_sha256="a" * 64, fetched_at=now, n_observations=1))
        s.flush()
        px = {sym: 100.0 for sym in ("XOM", "CVX", "UNG")}
        for i in range(120):
            d = date(2024, 1, 1) + timedelta(days=i)
            for sym in px:
                px[sym] *= 1 + rng.gauss(0, 0.01)
                s.add(MarketObservation(series_key=f"yahoo:{sym}", obs_date=d, value=px[sym]))
        for k in range(n_storms):
            sid = f"S{k:02d}"
            s.add(HistoricalStorm(
                storm_id=sid, name=f"STORM{k}", year=2000 + k, basin="NA", region="North Atlantic / Gulf of Mexico", event_type="hurricane",
                start_datetime=now, end_datetime=now, n_observations=2, n_original_observations=2, gulf_of_mexico_entered=True,
                min_lat=0, max_lat=1, min_lon=0, max_lon=1, source="NOAA IBTrACS", source_version="v04r01", source_url="u",
                source_subset="s", ingestion_timestamp=now, data_quality_status="ok", content_hash="h", max_category_normalized=4,
                max_category_in_gulf=4, max_wind_kt=120))
            s.flush()
            for sym in ("XOM", "CVX", "UNG"):
                car = (cars or {}).get(sym, 0.0) / 100 if cars else 0.0
                s.add(EventStudyResult(storm_id=sid, series_key=f"yahoo:{sym}", anchor="gulf_entry", anchor_date=date(2000 + k, 9, 1),
                                       t0_date=date(2000 + k, 9, 1), status="ok", n_estimation=220, overlap=(k % overlap_every == 0),
                                       windows={"0,5": {"car": car + rng.gauss(0, 0.005), "raw_return": 0.0, "t_stat": 0.0, "n_days": 6}},
                                       computed_at=now))
            if bsee and k < 3:
                s.add(BseeStormShutin(storm_key=f"{2000 + k}:S", storm_label="S", storm_name=f"STORM{k}", year=2000 + k, storm_id=sid,
                                      match_method="name_year", n_reports_listed=2, n_reports_used=2, max_oil_shut_in_pct=20.0 + 30 * k,
                                      note="n", computed_at=now))
        s.commit()
    return factory


@pytest.fixture
def wired(monkeypatch):
    def wire(factory):
        monkeypatch.setattr(fusion_service, "get_sessionmaker", lambda: factory)
        monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    return wire


Q = ParsedQuery(intent="event_impact", event_type="hurricane", event_category=4, region="Gulf of Mexico", confidence=1.0, parser="rules")


def test_fusion_reports_a_clear_effect_when_one_exists(wired):
    wired(seed(cars={"XOM": 3.0, "CVX": 3.0, "UNG": 3.0}))
    out = fusion_service.run_fusion(Q)
    p = out.portfolio
    assert out.status == "ok" and p.symbols == ["CVX", "UNG", "XOM"] and p.covered_weight_pct == 65.0 and p.uncovered_weight_pct == 35.0
    assert p.all_analogs.n == 12 and p.all_analogs.median == pytest.approx(0.65 * 3.0, abs=0.1)     # weights are the user's real weights
    assert p.all_analogs.grade == "indicative" and p.median_usd == pytest.approx(1_240_000 * p.all_analogs.median / 100, abs=1)
    assert "indistinguishable" not in out.conclusion and "12 comparable storms" in out.conclusion
    assert out.analogs["n_selected"] == 12 and out.analogs["selection_rule"]["min_category"] == 3
    assert not any(c.used_in_estimate for c in out.context_layers)


def test_fusion_says_so_when_there_is_no_effect_and_flags_the_phase10_assumption(wired):
    from app.quant.risk_engine import scenario_hurricane
    wired(seed(cars={"XOM": 0.0, "CVX": 0.0, "UNG": 0.0}))
    out = fusion_service.run_fusion(Q, scenario=scenario_hurricane(portfolio_service.get_portfolio()))
    assert out.portfolio.all_analogs.grade == "not_distinguishable_from_zero" and "indistinguishable from zero" in out.conclusion
    assert out.portfolio.scenario_change_pct == pytest.approx(3.7) and out.portfolio.scenario_vs_history == "above_historical_range"
    xom = next(a for a in out.assets if a.symbol == "XOM")
    assert xom.scenario_shock_pct == 5.0 and xom.scenario_vs_history == "above_historical_range"
    other = next(a for a in out.assets if a.symbol == "OTHER")
    assert not other.covered and other.stats is None                                    # no data -> no number
    assert any("Other assets" in x for x in out.limitations)


def test_independent_only_sensitivity_and_physical_context(wired):
    wired(seed(n_storms=12, overlap_every=2))
    out = fusion_service.run_fusion(Q)
    assert out.portfolio.independent_only.n == 6 and out.portfolio.all_analogs.n == 12
    assert out.physical_context["n_storms_with_bsee"] == 3 and out.physical_context["median_max_oil_shut_in_pct"] == 50.0
    assert any(c.layer.startswith("Physical") for c in out.context_layers)
    assert out.historical_risk["days"] >= 60 and out.historical_risk["annualised_volatility_pct"] > 0


def test_too_few_storms_gives_no_estimate(wired):
    wired(seed(n_storms=3))
    out = fusion_service.run_fusion(Q)
    assert out.status == "insufficient_evidence" and "no quantitative estimate" in out.conclusion


def test_unsupported_and_unavailable_paths(wired, monkeypatch):
    eq = ParsedQuery(intent="event_impact", event_type="earthquake", confidence=1.0, parser="rules")
    assert fusion_service.run_fusion(eq).status == "unsupported_event"
    assert fusion_service.run_fusion(Q.model_copy(update={"event_type": "none"})).status == "unsupported_event"
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    out = fusion_service.run_fusion(Q)
    assert out.status == "unavailable" and out.portfolio is None and out.meta.source == "demo"


def test_pipeline_runs_the_fusion_step_and_exposes_it(wired):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import historical_service
    factory = seed(cars={"XOM": 1.0, "CVX": 1.0, "UNG": 1.0})
    wired(factory)
    body = TestClient(app).post("/api/query", json={"query": "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?"}).json()
    steps = {s["step"]: s["status"] for s in body["steps"]}
    assert steps["fusion"] == "completed" and body["fusion"]["status"] == "ok"
    assert body["fusion"]["portfolio"]["all_analogs"]["n"] == 12
    assert body["scenario"] and body["fusion"]["portfolio"]["scenario_change_pct"] == pytest.approx(3.7)


def test_fusion_compares_only_the_requested_period(wired):
    wired(seed(n_storms=12, cars={"XOM": 2.0, "CVX": 2.0, "UNG": 2.0}))
    q = Q.model_copy(update={"year_from": 2003, "year_to": 2008})                  # seeded storms are years 2000..2011
    out = fusion_service.run_fusion(q)
    assert out.analogs["n_selected"] == 6 and out.analogs["selection_rule"]["year_from"] == 2003 and out.analogs["selection_rule"]["year_to"] == 2008
    assert out.status == "ok" and out.portfolio.all_analogs.n == 6
