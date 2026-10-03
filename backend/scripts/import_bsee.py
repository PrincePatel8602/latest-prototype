#!/usr/bin/env python
"""Import BSEE Gulf of Mexico storm shut-in statistics into PostgreSQL.

  python scripts/import_bsee.py              # fetch index + pages (raw kept), parse, verify, load, aggregate per storm
  python scripts/import_bsee.py --dry-run    # fetch + parse + report; nothing written to PostgreSQL
  python scripts/import_bsee.py --from-raw   # rebuild PostgreSQL from the stored raw pages (no network)
  python scripts/import_bsee.py --refresh    # re-download every page (changed pages become new immutable files)

BSEE publishes these as daily press releases (no structured file). Every page is verified to describe the storm it
is listed under; mismatched pages are stored as 'rejected' and their numbers are never used.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.historical import settings  # noqa: E402,F401  (loads .env)
from app.historical.database import get_engine, get_sessionmaker  # noqa: E402
from app.historical.models import HistoricalBase  # noqa: E402
from app.historical.physical.pipeline import run_bsee_ingest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-raw", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    import app.historical.physical.models  # noqa: F401,E402  (register tables)
    if a.dry_run:
        print(run_bsee_ingest(None, dry_run=True, refresh=a.refresh, from_raw=a.from_raw).render())
        return 0
    HistoricalBase.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        summary = run_bsee_ingest(session, refresh=a.refresh, from_raw=a.from_raw)
    print(summary.render())
    return 1 if summary.fetch_errors > 5 else 0


if __name__ == "__main__":
    raise SystemExit(main())
