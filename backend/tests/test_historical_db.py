"""Database / ingestion / hybrid-search tests. Use in-memory SQLite through the same SQLAlchemy models
as PostgreSQL. Skipped automatically when SQLAlchemy is not installed."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import sqlalchemy  # noqa: F401
    HAVE_SA = True
except ImportError:
    HAVE_SA = False

from tests.ibtracs_fixture import base_rows, bad_rows, write_csv
from tests.fake_pinecone import FakeIndex

NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)


@unittest.skipUnless(HAVE_SA, "sqlalchemy not installed")
class DbTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.historical.models import HistoricalBase
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        HistoricalBase.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = write_csv(self.dir / "ibtracs.NA.list.v04r01.csv", base_rows() + bad_rows())
        from app.historical.vector_store import HistoricalVectorStore
        self.index = FakeIndex()
        self.store = HistoricalVectorStore(self.index, "aegis-historical-events")

    def tearDown(self):
        self.tmp.cleanup()

    def _result(self, rows=None):
        from app.historical.ibtracs.download import load_snapshot
        from app.historical.ibtracs.pipeline import process_snapshot
        path = write_csv(self.dir / "ibtracs.NA.list.v04r01.csv", rows) if rows is not None else self.csv
        return process_snapshot(load_snapshot(path), min_year=None, now=NOW)

    def _ingest(self, mode="update", result=None, store="default"):
        from app.historical.ingest import IngestOptions, run_ingest
        return run_ingest(IngestOptions(min_year=None, mode=mode), session_factory=self.factory,
                          vector_store=self.store if store == "default" else store,
                          processed_dir=self.dir / "p", normalized_dir=self.dir / "n", result=result or self._result())

    def _count(self, model):
        from sqlalchemy import func, select
        with self.factory() as s:
            return s.scalar(select(func.count()).select_from(model))

    # ---- 8 / 9 / 14: insertion, uniqueness, repeat ingestion
    def test_first_ingest_inserts_storms_points_and_pinecone(self):
        from app.historical.models import HistoricalStorm, StormTrackPoint, IngestionRun
        s = self._ingest()
        self.assertEqual((s.inserted, s.updated, s.skipped, s.failed, s.errors), (5, 0, 0, 0, []))
        self.assertEqual(self._count(HistoricalStorm), 5)
        self.assertEqual(self._count(StormTrackPoint), 13)      # 7 + 2 + 2 + 1 + 1 valid points
        self.assertEqual(self._count(IngestionRun), 1)
        self.assertEqual((s.pinecone_created, s.pinecone_updated), (5, 0))
        self.assertEqual(len(self.index.records), 5)

    def test_repeat_ingestion_is_a_noop(self):
        from app.historical.models import HistoricalStorm, StormTrackPoint
        self._ingest()
        storms, points = self._count(HistoricalStorm), self._count(StormTrackPoint)
        s2 = self._ingest()
        self.assertEqual((s2.inserted, s2.updated, s2.skipped), (0, 0, 5))
        self.assertEqual((s2.pinecone_created, s2.pinecone_updated), (0, 0))
        self.assertEqual((self._count(HistoricalStorm), self._count(StormTrackPoint)), (storms, points))
        self.assertEqual(len(self.index.records), 5)

    def test_changed_data_updates_in_place_and_replaces_points(self):
        from app.historical.models import HistoricalStorm
        self._ingest()
        rows = base_rows() + bad_rows()
        rows[4][16] = rows[4][10] = "125"
        s = self._ingest(result=self._result(rows))
        self.assertEqual((s.inserted, s.updated, s.skipped), (0, 1, 4))
        self.assertEqual((s.pinecone_created, s.pinecone_updated), (0, 1))
        self.assertEqual(self._count(HistoricalStorm), 5)
        from app.historical import repository as repo
        with self.factory() as sess:
            self.assertEqual(repo.get_storm(sess, "2099001N20280").max_wind_kt, 125.0)

    def test_full_mode_rewrites_everything(self):
        self._ingest()
        s = self._ingest(mode="full")
        self.assertEqual((s.inserted, s.updated), (0, 5))
        self.assertEqual(s.pinecone_updated, 5)

    def test_storm_id_unique_constraint(self):
        from sqlalchemy.exc import IntegrityError
        from app.historical.models import HistoricalStorm
        self._ingest()
        with self.factory() as sess:
            row = sess.query(HistoricalStorm).first()
            sess.add(HistoricalStorm(**{c.name: getattr(row, c.name) for c in HistoricalStorm.__table__.columns if c.name != "id"}))
            with self.assertRaises(IntegrityError):
                sess.commit()

    def test_track_point_unique_constraint(self):
        from sqlalchemy.exc import IntegrityError
        from app.historical.models import StormTrackPoint
        self._ingest()
        with self.factory() as sess:
            p = sess.query(StormTrackPoint).first()
            sess.add(StormTrackPoint(**{c.name: getattr(p, c.name) for c in StormTrackPoint.__table__.columns if c.name != "id"}))
            with self.assertRaises(IntegrityError):
                sess.commit()

    def test_dry_run_writes_nothing(self):
        from app.historical.ingest import IngestOptions, run_ingest
        from app.historical.models import HistoricalStorm
        s = run_ingest(IngestOptions(min_year=None, dry_run=True), session_factory=self.factory,
                       vector_store=self.store, result=self._result())
        self.assertEqual((s.storms, s.inserted), (5, 0))
        self.assertEqual(self._count(HistoricalStorm), 0)
        self.assertEqual(len(self.index.records), 0)

    def test_pinecone_unavailable_does_not_break_postgres(self):
        from app.historical.models import HistoricalStorm
        s = self._ingest(store=None)            # None -> falls through to connect(); no API key in tests
        self.assertEqual(s.inserted, 5)
        self.assertIn("skipped", s.pinecone_status)
        self.assertEqual(self._count(HistoricalStorm), 5)

    # ---- provenance + pinecone metadata link
    def test_provenance_and_pinecone_link(self):
        from app.historical import repository as repo
        self._ingest()
        with self.factory() as sess:
            row = repo.get_storm(sess, "2099001N20280")
            d = repo.storm_to_dict(row)
        p = d["provenance"]
        self.assertEqual((p["source"], p["dataset_version"], p["subset"]), ("NOAA IBTrACS", "v04r01", "NA/all_years"))
        self.assertEqual(p["postgres"], {"table": "historical_storms", "id": row.id})
        self.assertEqual(p["pinecone"]["record_id"], "ibtracs:2099001N20280")
        self.assertTrue(p["pinecone"]["in_sync"])
        rec = self.index.records[("aegis-historical-events", "ibtracs:2099001N20280")]
        self.assertEqual(rec["postgres_id"], row.id)
        self.assertIn("Category 4", rec["chunk_text"])

    # ---- 12: hybrid search
    def test_structured_filter_and_category_scope(self):
        from app.historical import repository as repo
        self._ingest()
        with self.factory() as sess:
            gulf4 = repo.query_storms(sess, repo.StormFilter(gulf_only=True, min_category=4, category_scope="gulf"))
            self.assertEqual([r.name for r in gulf4], ["TESTGULF"])
            self.assertEqual([r.name for r in repo.query_storms(sess, repo.StormFilter(min_category=0, max_category=0))], ["TESTWS"])
            dist = repo.category_distribution(sess)
            self.assertEqual(sum(dist.values()), 5)

    def test_hybrid_search_combines_methods(self):
        from app.historical.filters import StormFilter
        from app.historical.search import SearchRequest, hybrid_search
        self._ingest()
        with self.factory() as sess:
            res = hybrid_search(sess, SearchRequest(
                filter=StormFilter(gulf_only=True, min_category=3, max_category=5, category_scope="gulf"),
                query_text="Category 4 hurricane Gulf of Mexico", category_target=4), self.store)
        self.assertEqual(res.retrieval_method, "structured+semantic")
        top = res.hits[0]
        self.assertEqual((top.storm["name"], top.retrieval_method), ("TESTGULF", "structured+semantic"))
        self.assertIsNotNone(top.similarity_score)
        self.assertEqual(top.storm["provenance"]["source"], "NOAA IBTrACS")

    def test_semantic_candidates_failing_structured_filter_are_dropped(self):
        from app.historical.filters import StormFilter
        from app.historical.search import SearchRequest, hybrid_search
        self._ingest()
        # make Pinecone "wrongly" return the non-Gulf storm even though the filter demands the Gulf
        class Sloppy:
            def search(self_inner, text, top_k=10, filter=None):
                from app.historical.vector_store import SemanticHit
                return [SemanticHit("ibtracs:2099010N15300", 0.99, {})]
        with self.factory() as sess:
            res = hybrid_search(sess, SearchRequest(filter=StormFilter(gulf_only=True), query_text="anything"), Sloppy())
        self.assertNotIn("TESTATL", [h.storm["name"] for h in res.hits])
        self.assertTrue(any("fail the structured filters" in n for n in res.notices))

    def test_no_pinecone_is_reported_not_hidden(self):
        from app.historical.filters import StormFilter
        from app.historical.search import SearchRequest, hybrid_search
        self._ingest()
        with self.factory() as sess:
            res = hybrid_search(sess, SearchRequest(filter=StormFilter(gulf_only=True), query_text="gulf"), None)
        self.assertEqual((res.semantic_status, res.retrieval_method), ("not_configured", "structured"))
        self.assertTrue(res.notices)
        self.assertTrue(all(h.similarity_score is None for h in res.hits))


if __name__ == "__main__":
    unittest.main()
