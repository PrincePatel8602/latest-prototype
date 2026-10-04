"""Hedging tests: maths with known answers, the service on seeded prices + storm windows, and routing."""
import random
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.analytics.models  # noqa: F401
import app.historical.market.models  # noqa: F401
import app.historical.physical.models  # noqa: F401
from app.analytics import hedging as hg
from app.analytics.models import EventStudyResult
from app.historical import runtime
from app.historical.market.models import MarketObservation, MarketSeries
from app.historical.models import HistoricalBase, HistoricalStorm
from app.schemas.query import ParsedQuery
from app.services import hedging_service


def gauss(n, sd, seed):
    rng = random.Random(seed)
    return [rng.gauss(0, sd) for _ in range(n)]


# ------------------------------------------------------------------ pure maths
def test_beta_and_r2_recover_a_known_relationship():
    h = gauss(500, 0.01, 1)
    noise = gauss(500, 0.002, 2)
    s = [0.7 * x + e for x, e in zip(h, noise)]
    beta, r2 = hg.beta_r2(s, h)
    assert beta == pytest.approx(0.7, abs=0.04) and r2 > 0.9
    assert hg.beta_r2([0.5 * x for x in h], h) == (pytest.approx(0.5), pytest.approx(1.0))
    with pytest.raises(ValueError):
        hg.beta_r2(s, [0.0] * 500)


def test_a_perfect_hedge_removes_all_variance_and_an_unrelated_one_removes_none():
    h = gauss(600, 0.01, 3)
    s = [0.6 * x for x in h]
    ev = hg.evaluate(s, h)
    assert ev["hedge_ratio"] == pytest.approx(0.6) and ev["in_sample_variance_reduction_pct"] == pytest.approx(100.0)
    assert ev["out_of_sample"]["variance_reduction_pct"] == pytest.approx(100.0, abs=0.01) and ev["after"]["volatility_pct"] == pytest.approx(0, abs=1e-6)
    junk = hg.evaluate(gauss(600, 0.01, 4), gauss(600, 0.01, 5))
    assert junk["in_sample_variance_reduction_pct"] < 3 and abs(junk["correlation"]) < 0.15


def test_out_of_sample_check_exposes_an_unstable_hedge():
    """Relationship holds in the old data but flips sign in the latest year: in-sample looks fine, out-of-sample is negative."""
    h = gauss(756, 0.01, 6)
    noise = gauss(756, 0.002, 7)
    s = [(0.8 if i < 504 else -0.8) * x + e for i, (x, e) in enumerate(zip(h, noise))]
    ev = hg.evaluate(s, h)
    assert ev["out_of_sample"]["variance_reduction_pct"] < 0 and ev["out_of_sample"]["train_days"] == 504 and ev["out_of_sample"]["test_days"] == 252


def test_too_little_history_returns_none():
    assert hg.evaluate(gauss(100, 0.01, 8), gauss(100, 0.01, 9)) is None


def test_trim_effect_matches_hand_calculation():
    a, b = gauss(400, 0.01, 10), gauss(400, 0.03, 11)
    r = hg.trim_effect({"A": a, "B": b}, {"A": 0.3, "B": 0.3}, "B", 0.5)
    assert r["weight_before_pct"] == 30 and r["weight_after_pct"] == 15 and r["volatility_after_pct"] < r["volatility_before_pct"]
    assert r["volatility_reduction_pct"] == pytest.approx(100 * (1 - r["volatility_after_pct"] / r["volatility_before_pct"]))
    assert hg.trim_effect({"A": a, "B": b}, {"A": 0.3, "B": 0.3}, "B", 0.0)["volatility_reduction_pct"] == pytest.approx(0)


def test_storm_windows_uses_joint_sample_and_hedged_arithmetic():
    sleeve = {"s1": 0.04, "s2": -0.06, "s3": 0.01, "s9": 0.5}
    hedge = {"s1": 0.05, "s2": -0.08, "s3": 0.0}
    out = hg.storm_windows(sleeve, hedge, 0.5)
    assert out["n"] == 3 and out["hedged"]["median"] == pytest.approx(0.01 * 100) and out["unhedged"]["median"] == pytest.approx(1.0)
    assert out["dispersion_hedged_pct"] < out["dispersion_unhedged_pct"]
    assert hg.storm_windows({"a": 1.0}, {"b": 1.0}, 0.5) is None


# ------------------------------------------------------------------ service on seeded data
def seed(spy_unrelated=True):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    n = 800
    start = now.date() - timedelta(days=n * 7 // 5 + 5)
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    sector = gauss(n, 0.012, 20)                                 # common energy factor
    rets = {"XLE": sector, "SPY": gauss(n, 0.01, 21),
            "XOM": [0.9 * x + e for x, e in zip(sector, gauss(n, 0.004, 22))],
            "CVX": [0.8 * x + e for x, e in zip(sector, gauss(n, 0.004, 23))],
            "UNG": [0.2 * x + e for x, e in zip(sector, gauss(n, 0.03, 24))],
            "USO": [0.5 * x + e for x, e in zip(sector, gauss(n, 0.01, 25))]}
    with factory() as s:
        for sym in rets:
            s.add(MarketSeries(series_key=f"yahoo:{sym}", source="yahoo", source_series_id=sym, name=sym,
                               category="etf" if sym in ("XLE", "SPY", "USO", "UNG") else "equity", unit="USD", frequency="daily",
                               source_url="u", raw_file_sha256="a" * 64, fetched_at=now, n_observations=n))
        s.flush()
        for sym, r in rets.items():
            p = 100.0
            rows = []
            for day, x in zip(dates, r):
                p *= 1 + x
                rows.append({"series_key": f"yahoo:{sym}", "obs_date": day, "value": p})
            s.bulk_insert_mappings(MarketObservation, rows)
        # 10 analog storms with stored 5-day raw returns for the holdings and the hedge instruments
        for k in range(10):
            sid = f"S{k:02d}"
            t0 = dates[100 + 60 * k]
            s.add(HistoricalStorm(storm_id=sid, name=f"STORM{k}", year=2000 + k, basin="NA", region="x", event_type="hurricane", start_datetime=now,
                                  end_datetime=now, n_observations=2, n_original_observations=2, gulf_of_mexico_entered=True, min_lat=0,
                                  max_lat=1, min_lon=0, max_lon=1, source="NOAA IBTrACS", source_version="v04r01", source_url="u",
                                  source_subset="s", ingestion_timestamp=now, data_quality_status="ok", content_hash="h",
                                  max_category_normalized=4, max_category_in_gulf=4, max_wind_kt=120))
            s.flush()
            i0 = dates.index(t0)
            for sym in ("XOM", "CVX", "UNG", "XLE", "USO"):
                px = {dd: v for dd, v in zip(dates, _cum(rets[sym]))}
                raw = px[dates[i0 + 5]] / px[dates[i0 - 1]] - 1
                s.add(EventStudyResult(storm_id=sid, series_key=f"yahoo:{sym}", anchor="gulf_entry", anchor_date=t0, t0_date=t0, status="ok",
                                       n_estimation=220, overlap=False, windows={"0,5": {"car": 0.0, "raw_return": raw, "t_stat": 0.0, "n_days": 6}},
                                       computed_at=now))
        s.commit()
    return factory


def _cum(r):
    p, out = 100.0, []
    for x in r:
        p *= 1 + x
        out.append(p)
    return out


@pytest.fixture
def wired(monkeypatch):
    def wire(factory):
        monkeypatch.setattr(hedging_service, "get_sessionmaker", lambda: factory)
        monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    return wire


GENERIC = ParsedQuery(intent="hedging", confidence=1.0, parser="rules")
STORM = ParsedQuery(intent="hedging", event_type="hurricane", event_category=4, region="Gulf of Mexico", confidence=1.0, parser="rules")


def test_service_ranks_the_sector_hedge_first_and_the_unrelated_one_last(wired):
    wired(seed())
    out = hedging_service.run_hedging(GENERIC)
    assert out.status == "ok"
    by = {c.series_key: c for c in out.candidates}
    assert out.candidates[0].series_key == "yahoo:XLE" and out.candidates[0].rank == 1
    assert by["yahoo:XLE"].out_of_sample["variance_reduction_pct"] > by["yahoo:USO"].out_of_sample["variance_reduction_pct"] > by["yahoo:SPY"].out_of_sample["variance_reduction_pct"]
    assert by["yahoo:SPY"].in_sample_variance_reduction_pct < 5 and by["yahoo:SPY"].rank == 3
    x = by["yahoo:XLE"]
    assert x.position == "short" and x.hedge_ratio > 0 and x.notional_usd == pytest.approx(abs(x.hedge_ratio) * 1_240_000)
    assert x.after["volatility_pct"] < x.before["volatility_pct"] and x.storm_windows is None          # no storm named -> no storm replay
    assert len(out.trim_options) == 2 and out.trim_options[0].trim_fraction == 0.25
    assert "Costs, options and taxes are not modeled" in out.conclusion and any("Options" in n for n in out.not_modeled)
    assert out.basis["sleeve_weight_pct"] == 65.0


def test_service_replays_hedges_through_storm_windows_when_a_storm_is_named(wired):
    wired(seed())
    out = hedging_service.run_hedging(STORM)
    x = next(c for c in out.candidates if c.series_key == "yahoo:XLE")
    assert x.storm_windows["n"] == 10 and x.storm_windows["dispersion_hedged_pct"] < x.storm_windows["dispersion_unhedged_pct"]
    spy = next(c for c in out.candidates if c.series_key == "yahoo:SPY")
    assert spy.storm_windows and spy.storm_windows["n"] == 10                           # SPY window returns computed from prices
    assert "comparable hurricane windows" in out.conclusion and out.storm_context["n_analogs_selected"] == 10


def test_unavailable_and_insufficient_paths(monkeypatch, wired):
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    assert hedging_service.run_hedging(GENERIC).status == "unavailable"
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    wired(sessionmaker(bind=engine))
    out = hedging_service.run_hedging(GENERIC)
    assert out.status == "insufficient_data" and out.candidates == [] and "cannot be evaluated" in out.conclusion


def test_pipeline_runs_hedging_for_a_hedging_question(wired, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    wired(seed())
    body = TestClient(app).post("/api/query", json={"query": "Show possible hedging strategies."}).json()
    steps = {s["step"]: s["status"] for s in body["steps"]}
    assert steps == {"exposure": "completed", "risk": "completed", "hedging": "completed"}
    assert body["hedging"]["candidates"][0]["series_key"] == "yahoo:XLE" and "not_implemented" not in steps.values()
