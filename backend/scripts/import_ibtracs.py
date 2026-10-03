#!/usr/bin/env python
"""Import NOAA IBTrACS into PostgreSQL + Pinecone.

  python scripts/import_ibtracs.py --download            # first run: fetch NA subset (v04r01), load everything
  python scripts/import_ibtracs.py --update              # re-run: only new/changed storms (default)
  python scripts/import_ibtracs.py --full                # rewrite every storm + re-sync Pinecone
  python scripts/import_ibtracs.py --dry-run             # parse/clean/report only; no DB, no Pinecone, no files
  python scripts/import_ibtracs.py --raw-file path/to/ibtracs.NA.list.v04r01.csv
  python scripts/import_ibtracs.py --raw-file path/to/ibtracs.since1980.list.v04r01.csv --subset since1980 --basins NA
  python scripts/import_ibtracs.py --min-year 1851       # whole North Atlantic record (default: 1980)
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:                                   # optional: load backend/.env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from app.historical.ingest import IngestOptions, run_ingest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="only new/changed storms (default)")
    mode.add_argument("--full", action="store_true", help="rewrite all storms and re-sync Pinecone")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--download", action="store_true", help="download a fresh raw snapshot from NOAA first")
    ap.add_argument("--raw-file", type=Path, help="use this IBTrACS csv instead of the latest stored snapshot")
    ap.add_argument("--subset", default="NA", choices=["NA", "since1980"])
    ap.add_argument("--min-year", type=int, default=1980)
    ap.add_argument("--basins", default="NA", help="comma list of IBTrACS basins to keep (default NA); ALL keeps every basin")
    ap.add_argument("--skip-pinecone", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    opts = IngestOptions(subset=a.subset, min_year=a.min_year,
                         basins=None if a.basins.upper() == "ALL" else tuple(b.strip().upper() for b in a.basins.split(",")), mode="full" if a.full else "update",
                         dry_run=a.dry_run, skip_pinecone=a.skip_pinecone, download=a.download, raw_file=a.raw_file)
    try:
        summary = run_ingest(opts)
    except Exception as e:             # noqa: BLE001
        print(f"INGESTION FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(summary.render())
    return 1 if (summary.failed or summary.errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
