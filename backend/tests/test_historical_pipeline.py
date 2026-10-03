"""Pure-Python pipeline tests (no database / network / Pinecone needed). Run: python -m unittest"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.historical.categories import category_from_wind_kt, event_type_from_category, kt_to_mph
from app.historical.events import SourceProvenance, build_document, build_event
from app.historical.geo import haversine_km, in_gulf
from app.historical.ibtracs.aggregate import summarize_all
from app.historical.ibtracs.clean import clean_rows, parse_float, parse_time
from app.historical.ibtracs.download import RawSnapshot, load_snapshot
from app.historical.ibtracs.parse import IBTrACSFormatError, read_rows
from app.historical.ibtracs.pipeline import process_snapshot, write_outputs
from tests.ibtracs_fixture import COLUMNS, base_rows, bad_rows, write_csv

NOW = datetime(2100, 1, 1, tzinfo=timezone.utc)


def _clean(tmp, rows, **kw):
    p = write_csv(Path(tmp) / "ibtracs.NA.list.v04r01.csv", rows)
    return clean_rows(read_rows(p), now=NOW, **kw)


class ParsingTests(unittest.TestCase):
    def test_units_row_skipped_and_columns_mapped(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_csv(Path(d) / "x.csv", base_rows())
            rows = list(read_rows(p))
            self.assertEqual(len(rows), len(base_rows()))
            self.assertEqual(rows[0][1]["SID"], "2099001N20280")

    def test_missing_required_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.csv"
            p.write_text("SID,NAME\nA,B\n")
            with self.assertRaises(IBTrACSFormatError):
                list(read_rows(p))

    def test_numeric_and_time_conversion(self):
        self.assertEqual(parse_float(" 12.5 "), 12.5)
        for tok in ("", " ", "NA", "nan", "-999", "abc", "inf"):
            self.assertIsNone(parse_float(tok), tok)
        self.assertEqual(parse_time("2005-08-28 18:00:00"), datetime(2005, 8, 28, 18, tzinfo=timezone.utc))
        self.assertIsNone(parse_time("28/08/2005"))


class CleaningTests(unittest.TestCase):
    def test_rejections_are_counted_with_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, base_rows() + bad_rows())
        self.assertEqual(rep.rejected_rows, 5)
        self.assertEqual(rep.reject_reasons["coordinates_out_of_range"], 1)
        self.assertEqual(rep.reject_reasons["invalid_timestamp"], 1)
        self.assertEqual(rep.reject_reasons["missing_coordinates"], 1)
        self.assertEqual(rep.reject_reasons["non_main_track_type"], 1)
        self.assertEqual(rep.reject_reasons["missing_storm_id"], 1)
        # every input row is accounted for
        self.assertEqual(rep.raw_rows, rep.valid_points + rep.rejected_rows + rep.duplicates_removed)

    def test_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, base_rows() + bad_rows())
        self.assertEqual(rep.duplicates_removed, 2)
        self.assertEqual(rep.duplicates_conflicting, 1)
        keys = [(p.storm_id, p.timestamp) for p in pts]
        self.assertEqual(len(keys), len(set(keys)))

    def test_impossible_values_blanked_not_row_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, base_rows() + bad_rows())
        p = next(x for x in pts if x.storm_id == "2099098N10100")
        self.assertIsNone(p.wind_kt)
        self.assertIsNone(p.pressure_mb)
        self.assertIn("wind_out_of_range:USA_WIND", p.quality_flags)
        self.assertIn("pressure_out_of_range:USA_PRES", p.quality_flags)

    def test_whitespace_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, base_rows() + bad_rows())
        ws = next(x for x in pts if x.storm_id == "2099097N10100")
        self.assertEqual((ws.lat, ws.lon, ws.wind_kt, ws.pressure_mb, ws.original_category), (20.0, -90.0, 55.0, 995.0, 0))
        blank_name = next(x for x in pts if x.storm_id == "2098005N25270" and x.timestamp.hour == 6)
        self.assertEqual(blank_name.name, "UNNAMED")
        self.assertIn("name_missing", blank_name.quality_flags)
        self.assertEqual(rep.missing_names, 1)

    def test_min_year_filter_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, base_rows(), min_year=2099)
        self.assertEqual(rep.filtered_out_min_year, 2)
        self.assertTrue(all(p.season >= 2099 for p in pts))

    def test_original_category_preserved_normalized_derived(self):
        with tempfile.TemporaryDirectory() as d:
            pts, _ = _clean(d, base_rows())
        peak = next(p for p in pts if p.wind_kt == 120)
        self.assertEqual((peak.original_category, peak.normalized_category), (4, 4))
        self.assertEqual(peak.category_source, "derived:saffir_simpson_kt:usa_wind")
        # source says 3 for 100kt -> 100 kt is Cat 3; and 40 kt/source 0 -> consistent
        self.assertEqual(category_from_wind_kt(100), 3)

    def test_category_thresholds_and_units(self):
        cases = {33: -1, 34: 0, 63: 0, 64: 1, 82: 1, 83: 2, 95: 2, 96: 3, 112: 3, 113: 4, 136: 4, 137: 5, 185: 5}
        for kt, cat in cases.items():
            self.assertEqual(category_from_wind_kt(kt), cat, kt)
        self.assertIsNone(category_from_wind_kt(None))
        self.assertAlmostEqual(kt_to_mph(100), 115.1, places=1)
        self.assertEqual(event_type_from_category(4), "hurricane")
        self.assertEqual(event_type_from_category(0), "tropical_storm")

    def test_category_disagreement_is_flagged_not_overwritten(self):
        rows = [__import__("tests.ibtracs_fixture", fromlist=["row"]).row(
            "2099050N10100", 2099, "TESTDIS", "2099-08-01 00:00:00", "20", "-90", "100", "960", "5")]
        with tempfile.TemporaryDirectory() as d:
            pts, rep = _clean(d, rows)
        self.assertEqual(pts[0].original_category, 5)       # untouched
        self.assertEqual(pts[0].normalized_category, 3)     # derived from 100 kt
        self.assertEqual(rep.category_disagreements, 1)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            pts, self.rep = _clean(d, base_rows())
        self.storms = {s.storm_id: s for s in summarize_all(pts)}

    def test_gulf_storm_features(self):
        s = self.storms["2099001N20280"]
        self.assertEqual((s.name, s.year, s.basin), ("TESTGULF", 2099, "NA"))
        self.assertEqual(s.max_wind_kt, 120.0)
        self.assertEqual(s.min_pressure_mb, 940.0)
        self.assertEqual(s.max_category_normalized, 4)
        self.assertEqual(s.max_category_original, 4)
        self.assertEqual(s.n_observations, 7)
        self.assertEqual(s.n_original_observations, 6)            # one interpolated row
        self.assertEqual(s.duration_hours, 30.0)
        self.assertTrue(s.gulf_of_mexico_entered)
        self.assertEqual(s.max_category_in_gulf, 4)
        self.assertEqual(s.landfall_indicator_observations, 2)
        self.assertEqual(s.region, "North Atlantic / Gulf of Mexico")
        self.assertEqual(s.data_quality_status, "ok")

    def test_track_length_matches_independent_haversine(self):
        s = self.storms["2099001N20280"]
        pts = [(24.0, -85.0), (25.0, -86.0), (26.0, -87.0), (27.0, -88.0), (28.5, -89.5), (30.0, -90.0)]
        expected = sum(haversine_km(*a, *b) for a, b in zip(pts, pts[1:]))
        self.assertAlmostEqual(s.track_length_km, round(expected, 1), places=1)
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.195, places=1)

    def test_non_gulf_and_missing_pressure(self):
        s = self.storms["2099010N15300"]
        self.assertFalse(s.gulf_of_mexico_entered)
        self.assertIsNone(s.max_category_in_gulf)
        self.assertIsNone(s.min_pressure_mb)
        self.assertEqual(s.data_quality_status, "partial")
        self.assertEqual(s.region, "North Atlantic")

    def test_unnamed_and_hash_stability(self):
        self.assertEqual(self.storms["2098005N25270"].name, "UNNAMED")
        with tempfile.TemporaryDirectory() as d:
            pts, _ = _clean(d, base_rows())
        again = {s.storm_id: s for s in summarize_all(pts)}
        for k, s in self.storms.items():
            self.assertEqual(s.content_hash, again[k].content_hash)

    def test_hash_changes_when_data_changes(self):
        rows = base_rows()
        rows[4][16] = "125"; rows[4][10] = "125"            # change a wind value
        with tempfile.TemporaryDirectory() as d:
            pts, _ = _clean(d, rows)
        changed = {s.storm_id: s for s in summarize_all(pts)}
        self.assertNotEqual(self.storms["2099001N20280"].content_hash, changed["2099001N20280"].content_hash)
        self.assertEqual(self.storms["2099010N15300"].content_hash, changed["2099010N15300"].content_hash)

    def test_gulf_polygon_sanity(self):
        self.assertTrue(in_gulf(27.0, -90.0))
        self.assertFalse(in_gulf(25.0, -60.0))
        self.assertFalse(in_gulf(14.0, -75.0))   # Caribbean


class EventAndDocumentTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            pts, _ = _clean(d, base_rows())
        self.s = next(s for s in summarize_all(pts) if s.storm_id == "2099001N20280")
        self.prov = SourceProvenance("NOAA IBTrACS", "v04r01", "https://example/ibtracs.NA.csv", "NA/min_year>=1980",
                                     "2026-10-03T00:00:00+00:00", "abc123")

    def test_event_shape_and_provenance(self):
        e = build_event(self.s, self.prov)
        self.assertEqual(e["event_id"], "ibtracs:2099001N20280")
        self.assertEqual(e["event_type"], "hurricane")
        self.assertEqual(e["hazard_features"]["max_category"], 4)
        self.assertEqual(e["hazard_features"]["max_wind_mph"], 138.1)
        sm = e["source_metadata"]
        self.assertEqual((sm["source"], sm["source_version"], sm["source_record_id"]),
                         ("NOAA IBTrACS", "v04r01", "2099001N20280"))
        json.dumps(e)  # serialisable

    def test_document_is_factual_and_deterministic(self):
        d1, d2 = build_document(self.s, self.prov), build_document(self.s, self.prov)
        self.assertEqual(d1, d2)
        for needle in ("Testgulf", "2099", "Category 4", "120.0 kt", "940.0 mb", "Gulf of Mexico", "NOAA IBTrACS v04r01"):
            self.assertIn(needle, d1)
        for forbidden in ("price", "market", "return", "%"):
            self.assertNotIn(forbidden, d1.lower())


class OutputAndReproducibilityTests(unittest.TestCase):
    def test_process_write_and_regenerate_identically(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "raw").mkdir()
            csv_path = write_csv(d / "raw" / "ibtracs.NA.list.v04r01.csv", base_rows() + bad_rows())
            before = csv_path.read_bytes()
            snap = load_snapshot(csv_path)
            self.assertEqual((snap.version, snap.subset), ("v04r01", "NA"))
            r1 = process_snapshot(snap, min_year=None, now=NOW)
            out1 = write_outputs(r1, d / "processed", d / "normalized")
            first = {k: v.read_bytes() for k, v in out1.items()}
            # regenerate from raw only
            for v in out1.values():
                v.unlink()
            r2 = process_snapshot(load_snapshot(csv_path), min_year=None, now=NOW)
            out2 = write_outputs(r2, d / "processed", d / "normalized")
            self.assertEqual(first, {k: v.read_bytes() for k, v in out2.items()})
            self.assertEqual(before, csv_path.read_bytes())             # raw untouched
            rep = json.loads(out2["report"].read_text())
            self.assertEqual(rep["quality"]["rejected_rows"], 5)
            self.assertEqual(len(r2.events), len(r2.storms))
            self.assertEqual(len(r2.documents), len(r2.storms))

    def test_manifest_hash_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            csv_path = write_csv(d / "ibtracs.NA.list.v04r01.csv", base_rows())
            snap = load_snapshot(csv_path)
            (d / "manifest.json").write_text(json.dumps({
                "source": snap.source, "version": snap.version, "subset": snap.subset, "url": snap.url,
                "downloaded_at": snap.downloaded_at, "bytes": snap.bytes, "sha256": snap.sha256}))
            load_snapshot(csv_path)                                    # ok
            csv_path.write_text(csv_path.read_text() + "\n")           # tamper
            with self.assertRaises(ValueError):
                load_snapshot(csv_path)


if __name__ == "__main__":
    unittest.main()
