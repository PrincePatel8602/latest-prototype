"""Event-study maths on SYNTHETIC prices with a known answer (seeded noise)."""
import random
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import event_study as es


def business_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def build(n=500, alpha=0.0002, beta=1.2, noise=0.004, shock=None, seed=7):
    """Benchmark + asset prices where asset = alpha + beta*market + noise (+ optional abnormal shock {day_index: r})."""
    rng = random.Random(seed)
    dates = business_days(date(2004, 1, 5), n)
    pb, pa, rm = [100.0], [50.0], []
    for i in range(1, n):
        m = rng.gauss(0.0004, 0.01)
        a = alpha + beta * m + rng.gauss(0, noise) + (shock or {}).get(i, 0.0)
        rm.append(m)
        pb.append(pb[-1] * (1 + m))
        pa.append(pa[-1] * (1 + a))
    return dates, dict(zip(dates, pa)), dict(zip(dates, pb))


def test_ols_recovers_parameters_and_no_shock_gives_small_car():
    dates, asset, bench = build()
    anchor = dates[300]
    r = es.event_study(asset, bench, anchor)
    assert r.status == "ok" and r.t0 == anchor and r.n_est == 220
    assert r.beta == pytest.approx(1.2, abs=0.08) and r.alpha == pytest.approx(0.0002, abs=0.001)
    assert abs(r.windows["0,5"]["t_stat"]) < 3                 # nothing injected: should not look significant
    assert abs(r.windows["0,5"]["car"]) < 0.03


def test_injected_abnormal_return_is_detected_in_the_right_windows():
    dates, _, _ = build()
    i0 = 300
    dates, asset, bench = build(shock={i0 + 1: 0.06})          # +6% abnormal on t0+1
    r = es.event_study(asset, bench, dates[i0])
    assert r.windows["0,5"]["car"] == pytest.approx(0.06, abs=0.025)
    assert r.windows["-1,1"]["car"] == pytest.approx(0.06, abs=0.02)
    assert r.windows["0,5"]["t_stat"] > 3
    assert abs(r.windows["-5,-1"]["car"]) < 0.03               # before the shock: nothing
    assert r.windows["0,10"]["raw_return"] > 0.03


def test_car_is_sum_of_abnormal_returns_by_hand():
    dates, asset, bench = build(shock={301: 0.02})
    i0 = 300
    r = es.event_study(asset, bench, dates[i0])
    ra = es.simple_returns([asset[d] for d in dates])
    rb = es.simple_returns([bench[d] for d in dates])
    by_hand = sum(ra[i] - (r.alpha + r.beta * rb[i]) for i in range(i0, i0 + 6))
    assert r.windows["0,5"]["car"] == pytest.approx(by_hand, abs=1e-12)


def test_weekend_anchor_maps_to_next_trading_day_and_far_gap_is_rejected():
    dates, asset, bench = build()
    sat = dates[300] + timedelta(days=(5 - dates[300].weekday()) % 7 or 7)
    r = es.event_study(asset, bench, sat)
    assert r.status == "ok" and r.t0 > sat and (r.t0 - sat).days <= 2
    assert es.event_study(asset, bench, dates[-1] + timedelta(days=30)).status == "after_data_end"
    assert es.event_study(asset, bench, dates[0] - timedelta(days=30)).status == "before_data_start"


def test_insufficient_history_is_reported_not_guessed():
    dates, asset, bench = build()
    assert es.event_study(asset, bench, dates[60]).status == "insufficient_estimation"       # < 120 prior obs
    assert es.event_study(asset, bench, dates[-3]).status == "insufficient_event_window"     # window runs off the data
    assert es.event_study({}, bench, dates[300]).status == "no_data"


def test_nonpositive_price_in_window_is_flagged():
    dates, asset, bench = build()
    asset[dates[302]] = -5.0                                    # e.g. WTI on 2020-04-20
    r = es.event_study(asset, bench, dates[300])
    assert r.status == "nonpositive_price" and r.windows == {}


def test_assets_with_different_calendars_are_aligned_on_common_dates():
    dates, asset, bench = build()
    for d in dates[100:110]:
        asset.pop(d)                                            # holidays on the asset only
    r = es.event_study(asset, bench, dates[300])
    assert r.status == "ok" and r.t0 == dates[300] and r.n_est == 220   # missing asset days are dropped, never filled


def test_max_drawdown_and_vol_ratio():
    assert es.max_drawdown([100, 110, 99, 105]) == pytest.approx(99 / 110 - 1)
    assert es.max_drawdown([1, 2, 3]) == 0
    dates, asset, bench = build(shock={301: -0.08, 302: 0.07, 303: -0.06, 304: 0.05, 305: -0.05})
    r = es.event_study(asset, bench, dates[300])
    assert r.vol_ratio > 3 and r.max_drawdown < -0.05


def test_summarize_reports_small_samples_honestly():
    s = es.summarize([0.01, -0.02, 0.03])
    assert s["n"] == 3 and s["t_stat"] is None and "fewer than 5" in s["note"]
    s = es.summarize([0.01, 0.02, 0.03, 0.04, 0.05, -0.01])
    assert s["n"] == 6 and s["share_positive"] == pytest.approx(5 / 6) and s["t_stat"] > 0
    assert es.summarize([]) == {"n": 0}


def test_overlap_detection():
    ov = es.tradingday_overlap({"a": date(2005, 8, 26), "b": date(2005, 9, 20), "c": date(2005, 9, 10)})
    assert ov == {"a": ["c"], "c": ["a", "b"], "b": ["c"]}


# ------------------------------------------------------------------ runner against the database models
def test_runner_end_to_end_on_sqlite(tmp_path):
    from datetime import datetime, timezone
    from app.analytics import runner
    from app.analytics.models import EventStudyResult
    from app.historical.market.models import MarketObservation, MarketSeries
    from app.historical.models import HistoricalBase, HistoricalStorm, StormTrackPoint

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    dates, asset, bench = build(shock={301: 0.05})
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        for key, cat, series in (("yahoo:SPY", "etf", bench), ("yahoo:XOM", "equity", asset)):
            s.add(MarketSeries(series_key=key, source="yahoo", source_series_id=key[6:], name=key, category=cat, unit="USD",
                               frequency="daily", source_url="u", raw_file_sha256="x" * 64, fetched_at=now, n_observations=len(series)))
            s.flush()
            s.bulk_insert_mappings(MarketObservation, [{"series_key": key, "obs_date": d, "value": v} for d, v in series.items()])
        t0 = datetime.combine(dates[300], datetime.min.time(), tzinfo=timezone.utc)
        s.add(HistoricalStorm(
            storm_id="S1", name="TEST", year=2005, basin="NA", region="x", event_type="hurricane", start_datetime=t0, end_datetime=t0,
            n_observations=2, n_original_observations=2, gulf_of_mexico_entered=True, min_lat=0, max_lat=1, min_lon=0, max_lon=1,
            source="NOAA IBTrACS", source_version="v04r01", source_url="u", source_subset="s", ingestion_timestamp=now,
            data_quality_status="ok", content_hash="h"))
        s.flush()
        for ts, lat, lon in ((t0 - timedelta(days=3), 15.0, -50.0), (t0, 25.0, -90.0), (t0 + timedelta(days=1), 27.0, -91.0)):
            s.add(StormTrackPoint(storm_id="S1", timestamp=ts, latitude=lat, longitude=lon, track_type="main", source="x", source_version="v"))
        s.commit()

        out = runner.run_event_study(s)
        assert (out.storms, out.assets, out.rows) == (1, 1, 1)
        row = s.query(EventStudyResult).one()
        assert row.status == "ok" and row.anchor_date == dates[300] and row.series_key == "yahoo:XOM"
        assert row.windows["0,5"]["car"] == pytest.approx(0.05, abs=0.025)
        assert row.provenance["benchmark"] == "yahoo:SPY" and row.provenance["storm_source_version"] == "v04r01"
        runner.run_event_study(s)                                # regenerating must not duplicate
        assert s.query(EventStudyResult).count() == 1
        agg = runner.aggregate(s, window="0,5")
        assert agg["yahoo:XOM"]["n"] == 1
