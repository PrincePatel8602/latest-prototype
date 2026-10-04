"""Pinecone-layer tests that need neither the SDK nor a database."""
import unittest
from types import SimpleNamespace

from app.historical.filters import StormFilter, storm_matches
from app.historical.vector_store import (HistoricalVectorStore, build_metadata, build_record, to_pinecone_filter)
from tests.fake_pinecone import FakeIndex

STORM = {
    "event_id": "ibtracs:2099001N20280", "postgres_id": 7, "storm_id": "2099001N20280", "name": "TESTGULF",
    "year": 2099, "basin": "NA", "region": "North Atlantic / Gulf of Mexico", "event_type": "hurricane",
    "max_category_normalized": 4, "max_category_in_gulf": 4, "gulf_of_mexico_entered": True, "max_wind_kt": 120.0,
    "provenance": {"source": "NOAA IBTrACS", "dataset_version": "v04r01"}, "content_hash": "h1",
}


class VectorTests(unittest.TestCase):
    def test_metadata_links_back_to_postgres_and_drops_none(self):
        md = build_metadata({**STORM, "max_category_in_gulf": None})
        for k in ("event_id", "postgres_id", "storm_id", "name", "year", "basin", "region", "source", "source_version"):
            self.assertIn(k, md)
        self.assertEqual((md["postgres_id"], md["source_version"]), (7, "v04r01"))
        self.assertNotIn("max_category_in_gulf", md)
        self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in md.values()))

    def test_record_has_stable_id_and_text_field(self):
        r = build_record(STORM, "doc text")
        self.assertEqual((r["_id"], r["chunk_text"]), ("ibtracs:2099001N20280", "doc text"))

    def test_filter_translation(self):
        self.assertIsNone(to_pinecone_filter(StormFilter()))
        f = to_pinecone_filter(StormFilter(gulf_only=True, min_category=3, max_category=5, category_scope="gulf"))
        self.assertEqual(f, {"$and": [{"gulf_of_mexico_entered": {"$eq": True}},
                                      {"max_category_in_gulf": {"$gte": 3}}, {"max_category_in_gulf": {"$lte": 5}}]})
        self.assertEqual(to_pinecone_filter(StormFilter(basin="na")), {"basin": {"$eq": "NA"}})
        self.assertEqual(to_pinecone_filter(StormFilter(min_category=0)), {"max_category": {"$gte": 0}})  # 0 is a real value

    def test_is_active_and_python_predicate_mirror(self):
        self.assertFalse(StormFilter().is_active())
        self.assertTrue(StormFilter(min_category=0).is_active())         # 0 must count as an active filter
        d = {"storm_id": "a", "name": "X", "basin": "NA", "year": 2005, "event_type": "hurricane",
             "gulf_of_mexico_entered": True, "max_category_normalized": 5, "max_category_in_gulf": 3, "max_wind_kt": 150}
        self.assertTrue(storm_matches(d, StormFilter(min_category=5)))
        self.assertFalse(storm_matches(d, StormFilter(min_category=4, category_scope="gulf")))   # Gulf-scope uses in-Gulf peak
        self.assertTrue(storm_matches(d, StormFilter(gulf_only=True, year_from=2000, year_to=2010, basin="na")))
        self.assertFalse(storm_matches(d, StormFilter(name="rita")))

    def test_upsert_batches_and_is_idempotent(self):
        idx = FakeIndex()
        store = HistoricalVectorStore(idx, "ns")
        recs = [build_record({**STORM, "event_id": f"ibtracs:{i}", "storm_id": str(i)}, f"doc {i}") for i in range(200)]
        self.assertEqual(store.upsert(recs), 200)
        self.assertEqual(idx.upsert_calls, 3)             # 90 + 90 + 20
        store.upsert(recs)
        self.assertEqual(len(idx.records), 200)           # same ids overwrite, no duplicates

    def test_search_parses_dict_and_object_hits(self):
        idx = FakeIndex()
        store = HistoricalVectorStore(idx, "ns")
        store.upsert([build_record(STORM, "Category 4 hurricane in the Gulf of Mexico")])
        hits = store.search("Category 4 Gulf hurricane", top_k=3)
        self.assertEqual((hits[0].event_id, hits[0].metadata["postgres_id"]), ("ibtracs:2099001N20280", 7))

        class ObjIndex:   # SDK-style attribute access
            def search(self, *, namespace, top_k=None, inputs=None, filter=None):
                return SimpleNamespace(result=SimpleNamespace(hits=[SimpleNamespace(
                    id="ibtracs:x", score=0.5, fields={"name": "X"})]))
        h = HistoricalVectorStore(ObjIndex(), "ns").search("q")
        self.assertEqual((h[0].event_id, h[0].score), ("ibtracs:x", 0.5))


if __name__ == "__main__":
    unittest.main()
