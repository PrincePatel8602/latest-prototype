#!/usr/bin/env python
"""Import historical market / macro series (EIA, FRED, Yahoo) into PostgreSQL.

  python scripts/import_market.py                      # all series in app/historical/market/config.py
  python scripts/import_market.py --series yahoo:XOM eia:RWTC
  python scripts/import_market.py --dry-run            # download + clean + report, write nothing
  python scripts/import_market.py --from-raw           # rebuild PostgreSQL from the stored raw snapshots (no network)

Keys: FRED_API_KEY and EIA_API_KEY in .env. Yahoo needs none.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.historical import settings  # noqa: E402,F401  (loads .env)
from app.historical.market.config import BY_KEY, SERIES  # noqa: E402
from app.historical.market.pipeline import run_market_ingest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", nargs="*", help="series keys, e.g. yahoo:XOM (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-raw", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    unknown = [k for k in (a.series or []) if k not in BY_KEY]
    if unknown:
        print(f"unknown series: {unknown}\nknown: {sorted(BY_KEY)}", file=sys.stderr)
        return 2
    specs = [BY_KEY[k] for k in a.series] if a.series else list(SERIES)
    summary = run_market_ingest(specs=specs, dry_run=a.dry_run, from_raw=a.from_raw)
    print(summary.render())
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
