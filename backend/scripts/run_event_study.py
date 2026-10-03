#!/usr/bin/env python
"""Compute event-study statistics for every Gulf storm x price series and store them in PostgreSQL.

  python scripts/run_event_study.py            # (re)generates event_study_results; deterministic, no network
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.runner import aggregate, run_event_study  # noqa: E402
from app.historical.database import get_engine, get_sessionmaker  # noqa: E402
from app.historical.models import HistoricalBase  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    import app.analytics.models  # noqa: F401,E402  (register table)
    import app.historical.market.models  # noqa: F401,E402
    HistoricalBase.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        summary = run_event_study(session)
        print(summary.render())
        from sqlalchemy import select
        from app.historical.models import HistoricalStorm as S
        groups = {
            "all Gulf storms": None,
            "Gulf hurricanes (Cat>=1 while in Gulf)": set(session.scalars(select(S.storm_id).where(S.max_category_in_gulf >= 1))),
            "major Gulf hurricanes (Cat>=3 while in Gulf)": set(session.scalars(select(S.storm_id).where(S.max_category_in_gulf >= 3))),
        }
        for gname, ids in groups.items():
            for window, excl in (("-1,1", True), ("0,5", True), ("0,10", True), ("0,5", False)):
                label = "non-overlapping events" if excl else "SENSITIVITY: overlapping events kept (not independent)"
                print(f"\n--- {gname}: CAR[{window}] vs SPY market model; {label}; descriptive, not causal ---")
                for key, s in aggregate(session, storm_ids=ids, window=window, exclude_overlap=excl).items():
                    if s["n"]:
                        t = f"{s['t_stat']:.2f}" if s.get("t_stat") is not None else "n/a"
                        print(f"{key:<14} n={s['n']:<3} mean={s['mean']*100:+6.2f}%  median={s['median']*100:+6.2f}%  "
                              f"pos={s['share_positive']*100:3.0f}%  t={t:>6}  (overlap-excluded {s['excluded_overlap']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
