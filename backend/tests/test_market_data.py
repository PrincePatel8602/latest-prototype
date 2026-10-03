"""Market-data layer tests: parsing/cleaning per source, raw store, idempotent PostgreSQL upsert.
All payloads are small SYNTHETIC samples in the exact shape each API returns (no network)."""
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.historical.market import pipeline
from app.historical.market.clean import clean
from app.historical.market.config import BY_KEY
from app.historical.market.models import MarketObservation, MarketSeries
from app.historical.models import HistoricalBase

FRED = {"observations": [
    {"date": "2005-08-26", "value": "4.10"}, {"date": "2005-08-29", "value": "4.15"},
    {"date": "2005-09-05", "value": "."},                      # FRED's missing marker (holiday)
    {"date": "bad-date", "value": "1"}, {"date": "2005-09-06", "value": "abc"},
    {"date": "2005-08-29", "value": "4.16"},                   # duplicate date: later row wins
    {"date": "2999-01-01", "value": "1"}]}
EIA = [{"response": {"total": 3, "data": [{"period": "2020-04-20", "value": "-36.98"}, {"period": "2020-04-21", "value": "8.91"}]}},
       {"response": {"total": 3, "data": [{"period": "2020-04-22", "value": None}]}}]


def yahoo(closes, ts0=1124755200):
    n = len(closes)
    return {"chart": {"result": [{"meta": {"gmtoffset": -14400}, "timestamp": [ts0 + 86400 * i for i in range(n)],
                                  "indicators": {"quote": [{"open": closes, "high": closes, "low": closes, "close": closes,
                                                            "volume": [100] * n}],
                                                 "adjclose": [{"adjclose": closes}]}}]}}


def test_fred_cleaning_counts_every_reject():
    obs, rep = clean(BY_KEY["fred:DGS10"], FRED)
    assert [o.obs_date.isoformat() for o in obs] == ["2005-08-26", "2005-08-29"]
    assert obs[1].value == 4.16                                  # duplicate resolved to the later row
    assert rep.raw_rows == 7 and rep.valid == 2 and rep.duplicates_removed == 1
    assert dict(rep.reject_reasons) == {"missing_value": 1, "invalid_date": 1, "non_numeric": 1, "future_date": 1}
    assert rep.raw_rows == rep.valid + rep.rejected + rep.duplicates_removed


def test_oil_negative_price_is_kept_but_negative_equity_is_rejected():
    obs, rep = clean(BY_KEY["eia:RWTC"], EIA)                    # WTI really closed at -36.98 on 2020-04-20
    assert [o.value for o in obs] == [-36.98, 8.91] and dict(rep.reject_reasons) == {"missing_value": 1}
    obs, rep = clean(BY_KEY["yahoo:XOM"], yahoo([50.0, -1.0, 0.0, 51.0]))
    assert len(obs) == 2 and dict(rep.reject_reasons) == {"negative_value": 1, "zero_price": 1}


def test_yahoo_parser_keeps_ohlcv_and_uses_exchange_date():
    obs, _ = clean(BY_KEY["yahoo:XOM"], yahoo([60.0, 61.5]))
    assert obs[0].open == obs[0].high == obs[0].adj_close == 60.0 and obs[0].volume == 100
    assert obs[1].obs_date > obs[0].obs_date


@pytest.fixture(autouse=True)
def restore_fetch():
    original = pipeline.fetcher.fetch
    yield
    pipeline.fetcher.fetch = original


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    monkeypatch.setattr(pipeline, "RAW_DIR", tmp_path / "raw")
    return sessionmaker(bind=engine, expire_on_commit=False)


def _run(db, payload, key="yahoo:XOM", monkeypatch=None, **kw):
    spec = BY_KEY[key]
    pipeline.fetcher.fetch = lambda s, c: (payload, "https://example.test/series")
    return pipeline.run_market_ingest(specs=[spec], session_factory=db, **kw)


def _count(db, model):
    with db() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_ingest_is_idempotent_and_updates_revisions(db):
    s1 = _run(db, yahoo([60.0, 61.0, 62.0]))
    r = s1.results[0]
    assert (r.status, r.inserted, r.updated, r.fetch) == ("ok", 3, 0, "downloaded")
    s2 = _run(db, yahoo([60.0, 61.0, 62.0]))
    r = s2.results[0]
    assert (r.inserted, r.updated, r.unchanged, r.fetch) == (0, 0, 3, "raw_reused")     # no new raw file either
    assert _count(db, MarketObservation) == 3 and _count(db, MarketSeries) == 1
    s3 = _run(db, yahoo([60.0, 61.0, 63.5, 64.0]))                                     # one revision + one new day
    r = s3.results[0]
    assert (r.inserted, r.updated, r.unchanged) == (1, 1, 2)
    assert _count(db, MarketObservation) == 4


def test_provenance_raw_files_and_from_raw_rebuild(db, tmp_path):
    _run(db, yahoo([60.0, 61.0]))
    with db() as s:
        series = s.scalar(select(MarketSeries))
        assert series.source == "yahoo" and "unofficial" in series.source_note and series.n_observations == 2
        assert series.source_url == "https://example.test/series" and len(series.raw_file_sha256) == 64
        assert "api_key" not in series.source_url
        sha = series.raw_file_sha256
    manifests = list((tmp_path / "raw").rglob("manifest.json"))
    assert len(manifests) == 1 and json.loads(manifests[0].read_text())["sha256"] == sha

    pipeline.fetcher.fetch = lambda *a: (_ for _ in ()).throw(AssertionError("network must not be used"))
    with db() as s:                                           # wipe the table, rebuild purely from the raw snapshot
        s.query(MarketObservation).delete(); s.commit()
    r = pipeline.run_market_ingest(specs=[BY_KEY["yahoo:XOM"]], session_factory=db, from_raw=True).results[0]
    assert (r.status, r.inserted, r.fetch) == ("ok", 2, "from_raw")


def test_raw_tampering_is_detected(db, tmp_path):
    _run(db, yahoo([60.0, 61.0]))
    raw = next((tmp_path / "raw").rglob("XOM.json"))
    raw.write_text(raw.read_text().replace("60.0", "99.0"))
    r = pipeline.run_market_ingest(specs=[BY_KEY["yahoo:XOM"]], session_factory=db, from_raw=True).results[0]
    assert r.status == "error" and "manifest" in r.error


def test_errors_are_reported_not_hidden_and_isolated_per_series(db):
    def fetch(spec, client):
        if spec.key == "yahoo:CVX":
            raise RuntimeError("HTTP 503")
        return yahoo([10.0, 11.0]), "https://example.test"
    pipeline.fetcher.fetch = fetch
    out = pipeline.run_market_ingest(specs=[BY_KEY["yahoo:CVX"], BY_KEY["yahoo:XOM"]], session_factory=db)
    assert [r.status for r in out.results] == ["error", "ok"] and out.failed == 1
    assert "503" in out.results[0].error and "ERROR" in out.render()


def test_dry_run_writes_nothing(db, tmp_path):
    out = _run(db, yahoo([60.0, 61.0]), dry_run=True)
    assert out.results[0].status == "dry_run" and _count(db, MarketObservation) == 0
    assert not (tmp_path / "raw").exists()


def test_every_catalogue_series_has_a_parser_and_unique_key():
    from app.historical.market.clean import PARSERS
    from app.historical.market.config import SERIES
    assert len({s.key for s in SERIES}) == len(SERIES) and all(s.source in PARSERS for s in SERIES)
    assert all(s.eia_route for s in SERIES if s.source == "eia")
