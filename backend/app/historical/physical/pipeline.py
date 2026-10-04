"""BSEE shut-in ingestion: index -> pages (raw kept) -> parse/verify -> bsee_reports -> per-storm aggregate -> IBTrACS link.

Safe to re-run: reports are keyed by URL, aggregates are recomputed wholesale from the stored reports.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.historical.models import HistoricalStorm
from app.historical.physical import fetch, parse
from app.historical.physical.models import BseeReport, BseeStormShutin

log = logging.getLogger("aegis.historical.bsee")
AGG_NOTE = ("Maxima over the verified BSEE reports for this storm; Gulf-wide figures that can include other concurrent "
            "storms, and a lower bound if some reports were unavailable (see n_reports_used vs n_reports_listed).")


@dataclass
class BseeSummary:
    entries: int = 0
    duplicate_listings: int = 0
    accepted: int = 0
    rejected: int = 0
    fetch_errors: int = 0
    no_percentages: int = 0
    reports_inserted: int = 0
    reports_updated: int = 0
    reports_unchanged: int = 0
    storms: int = 0
    storms_matched: int = 0
    unmatched: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    dry_run: bool = False

    def render(self) -> str:
        return "\n".join([
            "=== AEGIS BSEE shut-in ingestion ===" + (" (DRY RUN)" if self.dry_run else ""),
            f"Index entries:        {self.entries}  (duplicate listings of the same page: {self.duplicate_listings})",
            f"Verified reports:     {self.accepted}  (no percentages found: {self.no_percentages})",
            f"Rejected (mismatch):  {self.rejected}",
            f"Fetch errors:         {self.fetch_errors}",
            f"PostgreSQL reports:   inserted={self.reports_inserted} updated={self.reports_updated} unchanged={self.reports_unchanged}",
            f"Storms aggregated:    {self.storms}  matched to IBTrACS: {self.storms_matched}",
            f"Unmatched storms:     {self.unmatched}",
            f"Errors:               {len(self.errors)}" + "".join(f"\n  - {e}" for e in self.errors[:15]),
        ])


def _row_values(e: parse.IndexEntry, f: parse.ReleaseFacts | None, page: fetch.StoredPage | None, err: str | None, now) -> dict:
    name = parse.storm_name_from_label(e.storm_label).upper()
    if err or f is None:
        status, accepted, flags = "fetch_error", False, [err or "unknown"]
    elif not f.accepted:
        status, accepted, flags = "rejected", False, f.flags
    else:
        status, accepted, flags = ("ok" if (f.oil_shut_in_pct is not None or f.gas_shut_in_pct is not None) else "no_percentages"), True, f.flags
    v = dict(url=e.url, storm_label=e.storm_label, storm_name=name, index_year=e.year, accepted=accepted, status=status,
             flags=flags, ingestion_timestamp=now, source="BSEE storm activity statistics",
             raw_sha256=page.sha256 if page else None, fetched_at=page.fetched_at if page else None,
             report_date=None, oil_shut_in_pct=None, gas_shut_in_pct=None, oil_shut_in_bopd=None, gas_shut_in_mmcfd=None,
             platforms_evacuated=None, rigs_moved_off=None, shutin_sentence=None)
    if f is not None:
        v.update(report_date=f.report_date, shutin_sentence=f.shutin_sentence)
        if accepted:      # numbers from a page that does not describe this storm are never stored
            v.update(oil_shut_in_pct=f.oil_shut_in_pct, gas_shut_in_pct=f.gas_shut_in_pct, oil_shut_in_bopd=f.oil_shut_in_bopd,
                     gas_shut_in_mmcfd=f.gas_shut_in_mmcfd, platforms_evacuated=f.platforms_evacuated, rigs_moved_off=f.rigs_moved_off)
    return v


def _link_storms(session: Session, name: str, year: int) -> tuple[str | None, str]:
    rows = list(session.scalars(select(HistoricalStorm.storm_id).where(
        HistoricalStorm.name == name, HistoricalStorm.year == year)))
    if len(rows) == 1:
        return rows[0], "name_year"
    return None, "ambiguous" if rows else "unmatched"


def aggregate(session: Session, summary: BseeSummary | None = None) -> int:
    now = datetime.now(timezone.utc)
    groups: dict[tuple[int, str], list[BseeReport]] = defaultdict(list)
    for r in session.scalars(select(BseeReport)):
        groups[(r.index_year, r.storm_label)].append(r)
    session.execute(delete(BseeStormShutin))
    for (year, label), reps in sorted(groups.items()):
        used = [r for r in reps if r.accepted and (r.oil_shut_in_pct is not None or r.gas_shut_in_pct is not None)]
        name = reps[0].storm_name
        sid, how = _link_storms(session, name, year)
        oil = [r for r in used if r.oil_shut_in_pct is not None]
        peak = max(oil, key=lambda r: r.oil_shut_in_pct) if oil else None
        dates = [r.report_date for r in reps if r.accepted and r.report_date]
        session.add(BseeStormShutin(
            storm_key=f"{year}:{label}", storm_label=label, storm_name=name, year=year, storm_id=sid, match_method=how,
            n_reports_listed=len(reps), n_reports_used=len(used),
            max_oil_shut_in_pct=max((r.oil_shut_in_pct for r in used if r.oil_shut_in_pct is not None), default=None),
            max_gas_shut_in_pct=max((r.gas_shut_in_pct for r in used if r.gas_shut_in_pct is not None), default=None),
            max_platforms_evacuated=max((r.platforms_evacuated for r in used if r.platforms_evacuated is not None), default=None),
            peak_oil_date=peak.report_date if peak else None, first_report_date=min(dates, default=None),
            last_report_date=max(dates, default=None), source_urls=sorted(r.url for r in used), note=AGG_NOTE, computed_at=now))
        if summary is not None:
            summary.storms += 1
            if sid:
                summary.storms_matched += 1
            else:
                summary.unmatched.append(f"{year} {label} ({how})")
    session.flush()
    return len(groups)


def run_bsee_ingest(session: Session | None, *, dry_run: bool = False, refresh: bool = False, from_raw: bool = False,
                    client: httpx.Client | None = None, raw_dir=fetch.RAW_DIR) -> BseeSummary:
    s = BseeSummary(dry_run=dry_run)
    own = client is None
    client = client or httpx.Client()
    try:
        if from_raw:
            idx = sorted(raw_dir.glob("*/index.html"))
            if not idx:
                raise FileNotFoundError("no stored BSEE index; run without --from-raw first")
            html = idx[-1].read_text(encoding="utf-8")
        else:
            html, _ = fetch.store_index(client, raw_dir)
        entries = parse.parse_index(html)
        s.entries = len(entries)
        now = datetime.now(timezone.utc)
        existing = {} if session is None else {r.url: r for r in session.scalars(select(BseeReport))}
        by_url: dict[str, list[parse.IndexEntry]] = defaultdict(list)
        for e in entries:
            by_url[e.url].append(e)
        s.duplicate_listings = sum(len(v) - 1 for v in by_url.values())
        for url, listings in by_url.items():
            # the same page can be listed under two storms: keep the listing whose storm the page really describes
            best = None
            for e in listings:
                page, err, facts = None, None, None
                try:
                    page = fetch.cached_page(e.url, raw_dir) if from_raw else fetch.fetch_page(client, e.url, raw_dir, refresh)
                    if page is None:
                        raise FileNotFoundError("not in raw store")
                    facts = parse.parse_release(page.path.read_text(encoding="utf-8"), storm_label=e.storm_label,
                                                entry_year=e.year, listed_date=e.listed_date)
                except Exception as ex:                               # noqa: BLE001  (counted and listed, never hidden)
                    err = f"{type(ex).__name__}: {str(ex)[:120]}"
                vals = _row_values(e, facts, page, err, now)
                if best is None or (vals["accepted"] and not best[0]["accepted"]):
                    best = (vals, err, e)
            vals, err, e = best
            if err:
                s.fetch_errors += 1
                s.errors.append(f"{e.year} {e.storm_label} {url[-60:]}: {err}")
            if vals["status"] == "rejected":
                s.rejected += 1
            elif vals["accepted"]:
                s.accepted += 1
                s.no_percentages += vals["status"] == "no_percentages"
            if dry_run or session is None:
                continue
            old = existing.get(url)
            if from_raw and vals["status"] == "fetch_error" and old is not None:
                s.reports_unchanged += 1          # not in the raw store: keep what the original fetch recorded
                continue
            if old is None:
                session.add(BseeReport(**vals))
                s.reports_inserted += 1
            else:
                same = all(getattr(old, k) == v for k, v in vals.items() if k != "ingestion_timestamp")
                if same:
                    s.reports_unchanged += 1
                else:
                    for k, v in vals.items():
                        setattr(old, k, v)
                    s.reports_updated += 1
        if not dry_run and session is not None:
            session.flush()
            aggregate(session, s)
            session.commit()
    finally:
        if own:
            client.close()
    return s
