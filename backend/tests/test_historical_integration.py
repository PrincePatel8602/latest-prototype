"""Phase 11 wiring tests: basin filtering, raw-store adoption, the retrieval service, the REST API and the
Historical Agent. All data are the SYNTHETIC fixtures (TEST* storms, years 2098/2099); real-file checks
live in test_real_dataset_validation.py."""
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import historical as historical_api
from app.historical import runtime
from app.historical.ibtracs.download import adopt_into_raw_store, load_snapshot
from app.historical.ibtracs.pipeline import process_snapshot
from app.historical.ingest import IngestOptions, run_ingest
from app.historical.models import HistoricalBase
from app.historical.vector_store import HistoricalVectorStore
from app.main import app
from app.schemas.query import ParsedQuery
from app.services import historical_service
from tests.fake_pinecone import FakeIndex
from tests.ibtracs_fixture import base_rows, row, write_csv

NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)
client = TestClient(app)


def _rows():
    ep = [row("2099200N10250", 2099, "TESTPAC", "2099-07-01 00:00:00", "15.0", "-110.0", "90", "970", "2", basin="EP", sub="MM"),
          row("2099200N10250", 2099, "TESTPAC", "2099-07-01 06:00:00", "15.5", "-111.0", "100", "960", "3", basin="EP", sub="MM")]
    return base_rows() + ep


@pytest.fixture
def csv_path(tmp_path):
    return write_csv(tmp_path / "ibtracs.NA.list.v04r01.csv", _rows())


@pytest.fixture
def seeded(tmp_path, csv_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = HistoricalVectorStore(FakeIndex(), "aegis-historical-events")
    result = process_snapshot(load_snapshot(csv_path), min_year=None, basins=("NA",), now=NOW)
    summary = run_ingest(IngestOptions(min_year=None, basins=("NA",)), session_factory=factory, vector_store=store,
                         processed_dir=tmp_path / "p", normalized_dir=tmp_path / "n", result=result)
    assert summary.failed == 0 and summary.pinecone_status.startswith("ok")
    monkeypatch.setattr(historical_service, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    monkeypatch.setattr(runtime, "vector_store", lambda: store)

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[historical_api.get_session] = override
    yield factory, store
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ basin filter / raw store
def test_basin_filter_excludes_other_basins_and_reconciles(csv_path):
    res = process_snapshot(load_snapshot(csv_path), min_year=None, basins=("NA",), now=NOW)
    assert {s.basin for s in res.storms} == {"NA"}
    r = res.report
    assert r.filtered_out_basin == 2
    assert r.raw_rows == r.valid_points + r.rejected_rows + r.duplicates_removed + r.filtered_out_min_year + r.filtered_out_basin
    assert "basins=NA" in res.subset_label
    allb = process_snapshot(load_snapshot(csv_path), min_year=None, basins=None, now=NOW)
    assert {"NA", "EP"} <= {s.basin for s in allb.storms}


def test_adopt_into_raw_store_preserves_file_and_is_idempotent(csv_path, tmp_path):
    raw_dir = tmp_path / "raw"
    before = csv_path.read_bytes()
    a = adopt_into_raw_store(csv_path, raw_dir)
    b = adopt_into_raw_store(csv_path, raw_dir)
    assert csv_path.read_bytes() == before and a.path.read_bytes() == before
    assert a.path == b.path and len(list(raw_dir.rglob("ibtracs.*.csv"))) == 1
    manifest = json.loads(a.manifest_path.read_text())
    assert manifest["origin"] == "user_supplied_file" and manifest["sha256"] == a.sha256
    assert load_snapshot(a.path).origin == "user_supplied_file"      # manifest is re-validated against the bytes


# ------------------------------------------------------------------ service
def test_service_hybrid_search_with_provenance(seeded):
    r = historical_service.search(event_type="hurricane", region="Gulf of Mexico", category=4)
    assert r.status == "ok" and r.meta.source == "live"
    m = r.matches[0]
    assert m.storm.name == "TESTGULF" and m.storm.max_category_in_gulf == 4
    assert m.retrieval_method == "structured+semantic" and m.similarity_score is not None
    p = m.storm.provenance
    assert p["source"] == "NOAA IBTrACS" and p["dataset_version"] == "v04r01" and p["source_url"].startswith("https://")
    assert p["postgres"]["id"] == m.storm.postgres_id
    assert p["pinecone"]["record_id"] == "ibtracs:" + m.storm.storm_id and p["pinecone"]["in_sync"] is True
    assert r.dataset["storms_in_database"] == 3 and "TESTPAC" not in {x.storm.name for x in r.matches}
    assert "no market impact is inferred" in r.summary


def test_service_unsupported_event_and_unavailable(seeded, monkeypatch):
    r = historical_service.search(event_type="earthquake")
    assert r.status == "unsupported_event" and r.matches == []
    monkeypatch.setattr(runtime, "database_enabled", lambda: False)
    r = historical_service.search(event_type="hurricane")
    assert r.status == "unavailable" and r.matches == [] and r.meta.source == "demo"      # never fabricates data


def test_service_empty_database_reports_it(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(historical_service, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    r = historical_service.search(event_type="hurricane")
    assert r.status == "no_results" and "import_ibtracs" in r.summary


# ------------------------------------------------------------------ agent
def test_historical_agent_uses_postgres_backed_service(seeded):
    from app.agents.historical_agent import run_historical_agent
    parsed = ParsedQuery(intent="historical_search", event_type="hurricane", event_category=4, region="Gulf of Mexico",
                         confidence=0.9, parser="rules")
    out = run_historical_agent(parsed)
    assert out.status == "ok" and out.matches[0].storm.storm_id == "2099001N20280"


# ------------------------------------------------------------------ REST API
def test_api_search_storms_and_storm_detail(seeded):
    r = client.post("/api/historical/search", json={"gulf_of_mexico": True, "min_category": 3, "category_scope": "gulf",
                                                    "query": "gulf hurricane", "category_target": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [h["storm"]["name"] for h in body["hits"]] == ["TESTGULF"]
    h = body["hits"][0]
    assert h["retrieval_method"] == "structured+semantic" and h["storm"]["provenance"]["postgres"]["table"] == "historical_storms"

    lst = client.get("/api/historical/storms", params={"year": 2099}).json()
    assert lst["total"] == 2 and {s["name"] for s in lst["storms"]} == {"TESTGULF", "TESTATL"}

    d = client.get("/api/historical/storm/2099001N20280", params={"include_track": True}).json()
    assert d["name"] == "TESTGULF" and len(d["track"]) == d["n_observations"]
    assert client.get("/api/historical/storm/NOPE").status_code == 404
    assert client.get("/api/historical/status").json()["storms"] == 3


def test_api_semantic_results_are_reverified_against_filters(seeded):
    body = client.post("/api/historical/search", json={"min_category": 5, "query": "gulf hurricane"}).json()
    assert body["hits"] == []          # TESTGULF peaks at Cat 4: semantic similarity cannot override a structured filter


def test_api_503_when_database_not_configured():
    app.dependency_overrides.clear()
    assert client.get("/api/historical/storms").status_code == 503      # conftest removes DATABASE_URL


# ------------------------------------------------------------------ event-study exposure (Phase 12)
def _add_event_study(factory, car=0.0123):
    from datetime import date
    from app.analytics.models import EventStudyResult
    from app.historical.market.models import MarketSeries
    now = datetime.now(timezone.utc)
    with factory() as s:
        s.add(MarketSeries(series_key="yahoo:XOM", source="yahoo", source_series_id="XOM", name="Exxon Mobil", category="equity",
                           unit="USD", frequency="daily", source_url="u", raw_file_sha256="a" * 64, fetched_at=now, n_observations=1))
        s.flush()
        s.add(EventStudyResult(
            storm_id="2099001N20280", series_key="yahoo:XOM", anchor="gulf_entry", anchor_date=date(2099, 8, 21),
            t0_date=date(2099, 8, 21), status="ok", n_estimation=220, beta=1.1, overlap=False,
            windows={"0,5": {"car": car, "raw_return": 0.02, "t_stat": 1.5, "n_days": 6}},
            provenance={"benchmark": "yahoo:SPY"}, computed_at=now))
        s.commit()


def test_agent_attaches_stored_market_response(seeded):
    factory, _ = seeded
    _add_event_study(factory)
    r = historical_service.search(event_type="hurricane", region="Gulf of Mexico", category=4)
    m = r.matches[0].market_response
    assert [x.series_key for x in m] == ["yahoo:XOM"] and m[0].car == pytest.approx(0.0123) and m[0].t_stat == 1.5
    assert m[0].provenance["benchmark"] == "yahoo:SPY"
    assert "not a prediction" in r.market_response_note
    assert r.matches[0].storm.storm_id == "2099001N20280"


def test_agent_without_computed_event_study_returns_none_not_made_up(seeded):
    r = historical_service.search(event_type="hurricane", region="Gulf of Mexico", category=4)
    assert r.matches[0].market_response == [] and r.market_response_note is None


def test_api_event_study_endpoints(seeded):
    factory, _ = seeded
    assert client.get("/api/historical/event-study/2099001N20280").json()["computed"] is False
    _add_event_study(factory)
    body = client.get("/api/historical/event-study/2099001N20280").json()
    assert body["computed"] and body["results"][0]["car"] == pytest.approx(0.0123) and "not a prediction" in body["note"]
    assert client.get("/api/historical/event-study/NOPE").status_code == 404
    s = client.get("/api/historical/event-study-summary", params={"group": "hurricane"}).json()
    assert s["series"]["yahoo:XOM"]["n"] == 1 and s["series"]["yahoo:XOM"]["t_stat"] is None      # n < 5: no t-stat
    assert client.get("/api/historical/event-study-summary", params={"group": "bad"}).status_code == 422
