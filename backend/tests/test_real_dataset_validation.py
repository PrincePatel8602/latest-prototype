"""Validation against the REAL NOAA file (skipped until it is present).

Set IBTRACS_RAW_FILE=/path/to/ibtracs.NA.list.v04r01.csv, or run `import_ibtracs.py --download` first.
Expected values are the published best-track peaks (NHC): Katrina 2005 150 kt Cat 5, Rita 2005 155 kt Cat 5,
Harvey 2017 115 kt Cat 4, Ida 2021 130 kt Cat 4. These are checks, not data used by the application.
"""
import os
import unittest
from pathlib import Path

from app.historical.ibtracs.download import latest_snapshot, load_snapshot
from app.historical.ibtracs.pipeline import process_snapshot

EXPECTED = {("KATRINA", 2005): (150, 5), ("RITA", 2005): (155, 5), ("HARVEY", 2017): (115, 4), ("IDA", 2021): (130, 4)}


def _snapshot():
    env = os.getenv("IBTRACS_RAW_FILE")
    if env and Path(env).exists():
        return load_snapshot(Path(env))
    return latest_snapshot("NA") or latest_snapshot("since1980")


SNAP = _snapshot()


@unittest.skipIf(SNAP is None, "real IBTrACS file not available (set IBTRACS_RAW_FILE or run --download)")
class RealDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = process_snapshot(SNAP, min_year=1980, basins=("NA",))
        cls.by_key = {(s.name, s.year): s for s in cls.res.storms if s.basin == "NA"}

    def test_known_storms_present_and_correct(self):
        for key, (wind, cat) in EXPECTED.items():
            with self.subTest(storm=key):
                s = self.by_key.get(key)
                self.assertIsNotNone(s, f"{key} not found in real dataset")
                self.assertAlmostEqual(s.max_wind_kt, wind, delta=5)
                self.assertEqual(s.max_category_normalized, cat)
                self.assertEqual(s.max_category_original, cat)
                self.assertTrue(s.gulf_of_mexico_entered)
                self.assertGreater(s.track_length_km, 1000)

    def test_report_reconciles(self):
        r = self.res.report
        self.assertEqual(r.raw_rows, r.valid_points + r.rejected_rows + r.duplicates_removed
                         + r.filtered_out_min_year + r.filtered_out_basin)


if __name__ == "__main__":
    unittest.main()
