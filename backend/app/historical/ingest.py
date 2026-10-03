"""Orchestrates one ingestion run:

    RAW -> VALIDATE -> CLEAN -> NORMALISE (files)  -> POSTGRESQL (upsert) -> PINECONE (sync)

Safe to re-run: PostgreSQL identity is storm_id (unique) with content-hash change detection, and
Pinecone record ids are stable, so a second run inserts nothing and rewrites nothing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.historical import settings
from app.historical.ibtracs import download as dl
from app.historical.ibtracs.aggregate import group_by_storm
from app.historical.ibtracs.pipeline import ProcessingResult, format_report, process_snapshot, write_outputs

log = logging.getLogger("aegis.historical.ingest")


@dataclass
class IngestOptions:
    subset: str = "NA"
    min_year: int | None = 1980
    basins: tuple[str, ...] | None = ('NA',)   # since1980 is a GLOBAL file; keep North Atlantic by default
    mode: str = "update"                  # "update" = only new/changed, "full" = rewrite every storm
    dry_run: bool = False
    skip_pinecone: bool = False
    download: bool = False                # fetch a new raw snapshot from NOAA first
    raw_file: Path | None = None
    batch_size: int = 50


@dataclass
class IngestSummary:
    source: str = ""
    dataset_version: str = ""
    subset: str = ""
    download_status: str = "not_requested"
    dry_run: bool = False
    raw_rows: int = 0
    valid_points: int = 0
    rejected_rows: int = 0
    duplicates_removed: int = 0
    storms: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    pinecone_status: str = "not_run"
    pinecone_created: int = 0
    pinecone_updated: int = 0
    errors: list[str] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    quality_report_text: str = ""

    def render(self) -> str:
        lines = [
            "=== AEGIS historical ingestion ===",
            f"Source / version / subset: {self.source} / {self.dataset_version} / {self.subset}",
            f"Download:                  {self.download_status}",
            f"Raw rows:                  {self.raw_rows}",
            f"Cleaned (valid) points:    {self.valid_points}",
            f"Rejected rows:             {self.rejected_rows}",
            f"Duplicates removed:        {self.duplicates_removed}",
            f"Storms:                    {self.storms}",
            f"PostgreSQL:                {'DRY RUN (no writes)' if self.dry_run else 'written'}"
            f" | inserted={self.inserted} updated={self.updated} skipped={self.skipped} failed={self.failed}",
            f"Pinecone:                  {self.pinecone_status}"
            f" | created={self.pinecone_created} updated={self.pinecone_updated}",
            f"Errors:                    {len(self.errors)}",
        ]
        lines += [f"  - {e}" for e in self.errors[:20]]
        if self.quality_report_text:
            lines += ["", "--- data-quality report ---", self.quality_report_text]
        return "\n".join(lines)


def resolve_snapshot(opts: IngestOptions) -> tuple[dl.RawSnapshot, str]:
    if opts.raw_file:
        if opts.dry_run:
            return dl.load_snapshot(Path(opts.raw_file)), "skipped (using --raw-file)"
        return dl.adopt_into_raw_store(Path(opts.raw_file)), "skipped (user-supplied file preserved in raw store)"
    if opts.download:
        return dl.download(opts.subset), "downloaded"
    snap = dl.latest_snapshot(opts.subset)
    if snap is None:      # e.g. only the global since1980 file is stored; basin filtering selects the region
        for other in settings.SUPPORTED_SUBSETS:
            snap = dl.latest_snapshot(other)
            if snap is not None:
                break
    if snap is None:
        raise FileNotFoundError(
            f"No raw IBTrACS snapshot for subset {opts.subset!r} under {settings.RAW_DIR}. "
            f"Run with --download (needs internet) or pass --raw-file PATH.")
    return snap, "skipped (reusing existing raw snapshot)"


def run_ingest(opts: IngestOptions, *, session_factory: Callable | None = None, vector_store=None,
               processed_dir: Path = settings.PROCESSED_DIR, normalized_dir: Path = settings.NORMALIZED_DIR,
               result: ProcessingResult | None = None) -> IngestSummary:
    summary = IngestSummary(dry_run=opts.dry_run)
    started = datetime.now(timezone.utc)

    if opts.dry_run and opts.download:
        raise ValueError("--dry-run writes nothing, so it cannot be combined with --download")
    if result is None:
        snap, summary.download_status = resolve_snapshot(opts)
        result = process_snapshot(snap, min_year=opts.min_year, basins=opts.basins)
    rep = result.report
    summary.source, summary.dataset_version, summary.subset = result.snapshot.source, result.snapshot.version, result.subset_label
    summary.raw_rows, summary.valid_points = rep.raw_rows, rep.valid_points
    summary.rejected_rows, summary.duplicates_removed, summary.storms = rep.rejected_rows, rep.duplicates_removed, len(result.storms)
    summary.quality_report_text = format_report(result)

    if opts.dry_run:
        summary.pinecone_status = "skipped (dry run)"
        return summary

    summary.outputs = {k: str(v) for k, v in write_outputs(result, processed_dir, normalized_dir).items()}

    # ---------------- PostgreSQL
    from app.historical import repository as repo
    from app.historical.database import get_engine, get_sessionmaker
    from app.historical.models import HistoricalBase, IngestionRun

    if session_factory is None:
        HistoricalBase.metadata.create_all(get_engine())
        session_factory = get_sessionmaker()
    by_storm = group_by_storm(result.points)
    session = session_factory()
    touched: list[str] = []
    known = {} if opts.mode == "full" else repo.stored_hashes(session)   # one query instead of one per storm
    try:
        for i, s in enumerate(result.storms, start=1):
            if known.get(s.storm_id) == s.content_hash:
                summary.skipped += 1
                touched.append(s.storm_id)
                continue
            try:
                with session.begin_nested():
                    action, _ = repo.upsert_storm(session, s, by_storm[s.storm_id], result.provenance,
                                                  force=(opts.mode == "full"))
                setattr(summary, action, getattr(summary, action) + 1)
                touched.append(s.storm_id)
            except Exception as e:                                   # noqa: BLE001  (never hidden)
                summary.failed += 1
                summary.errors.append(f"postgres {s.storm_id}: {type(e).__name__}: {e}")
                log.exception("storm %s failed", s.storm_id)
            if i % opts.batch_size == 0:
                session.commit()
        session.commit()

        # ---------------- Pinecone
        if opts.skip_pinecone:
            summary.pinecone_status = "skipped (--skip-pinecone)"
        else:
            _sync_pinecone(session, summary, result, touched, vector_store, force=(opts.mode == "full"))

        run = IngestionRun(source=summary.source, source_version=summary.dataset_version, subset=summary.subset,
                           mode=opts.mode, started_at=started, finished_at=datetime.now(timezone.utc),
                           status="failed" if summary.failed or summary.errors else "ok",
                           raw_file_sha256=result.snapshot.sha256,
                           report={k: v for k, v in summary.__dict__.items() if k not in ("quality_report_text",)}
                           | {"quality": rep.to_dict() | {"reject_samples": rep.reject_samples[:20]}})
        repo.record_run(session, run)
        session.commit()
    finally:
        session.close()
    return summary


def _sync_pinecone(session, summary: IngestSummary, result: ProcessingResult, storm_ids: list[str],
                   vector_store, *, force: bool) -> None:
    from app.historical import repository as repo
    from app.historical import vector_store as vs
    from app.historical.events import event_id_for

    try:
        store = vector_store or vs.connect()
    except Exception as e:                                           # noqa: BLE001
        summary.pinecone_status = "error"
        summary.errors.append(f"pinecone connect: {type(e).__name__}: {e}")
        return
    if store is None:
        summary.pinecone_status = "skipped (PINECONE_API_KEY not set)"
        return

    pending = repo.storms_needing_pinecone_sync(session, storm_ids, force=force)
    records, first_time = [], 0
    for row in pending:
        d = repo.storm_to_dict(row)
        d["content_hash"] = row.content_hash
        records.append(vs.build_record(d, result.documents[event_id_for(row.storm_id)]))
        first_time += row.pinecone_synced_hash is None
    try:
        store.upsert(records)
    except Exception as e:                                           # noqa: BLE001
        summary.pinecone_status = "error"
        summary.errors.append(f"pinecone upsert: {type(e).__name__}: {e}")
        return                       # PostgreSQL stays correct; unsynced rows are retried next run
    repo.mark_pinecone_synced(session, pending, store.namespace)
    session.commit()
    summary.pinecone_created, summary.pinecone_updated = first_time, len(pending) - first_time
    summary.pinecone_status = f"ok (namespace={store.namespace})"
