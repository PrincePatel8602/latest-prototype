"""RAW -> CLEAN -> POSTGRESQL for market/macro series. Safe to re-run (unique (series, date); changed values updated)."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import httpx
from sqlalchemy import select, update

from app.historical import settings
from app.historical.market import fetch as fetcher
from app.historical.market.clean import MarketReport, Observation, clean
from app.historical.market.config import SERIES, SOURCE_NOTES, SeriesSpec
from app.historical.market.models import MarketObservation, MarketSeries

log = logging.getLogger("aegis.historical.market")
RAW_DIR = settings.DATA_ROOT / "raw" / "market"
_FIELDS = ("value", "open", "high", "low", "adj_close", "volume")


@dataclass
class SeriesResult:
    key: str
    status: str = "ok"                 # ok | error | dry_run
    fetch: str = ""                    # downloaded | raw_reused | from_raw
    report: MarketReport | None = None
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    error: str | None = None


@dataclass
class MarketSummary:
    results: list[SeriesResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def failed(self) -> int:
        return sum(r.status == "error" for r in self.results)

    def render(self) -> str:
        lines = ["=== AEGIS market-data ingestion ===" + (" (DRY RUN: nothing written to PostgreSQL)" if self.dry_run else "")]
        lines.append(f"{'series':<18}{'raw':>7}{'valid':>7}{'rej':>5}{'dup':>5}{'ins':>7}{'upd':>6}{'same':>7}  range / note")
        for r in self.results:
            if r.status == "error":
                lines.append(f"{r.key:<18}ERROR: {r.error}")
                continue
            p = r.report
            note = f"{p.first_date}..{p.last_date}" + (f"  rejects={dict(p.reject_reasons)}" if p.rejected else "")
            lines.append(f"{r.key:<18}{p.raw_rows:>7}{p.valid:>7}{p.rejected:>5}{p.duplicates_removed:>5}"
                         f"{r.inserted:>7}{r.updated:>6}{r.unchanged:>7}  {note}  [{r.fetch}]")
        lines.append(f"Series: {len(self.results)}  failed: {self.failed}")
        return "\n".join(lines)


# ------------------------------------------------------------------ raw store
def _slug(spec: SeriesSpec) -> Path:
    return RAW_DIR / spec.source / spec.source_series_id.replace("^", "_")


def latest_raw(spec: SeriesSpec) -> tuple[Path, dict] | None:
    base = _slug(spec)
    if not base.exists():
        return None
    for d in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True):
        m = d / "manifest.json"
        if m.exists():
            man = json.loads(m.read_text(encoding="utf-8"))
            return d / man["file"], man
    return None


def store_raw(spec: SeriesSpec, payload, url: str) -> tuple[Path, dict, bool]:
    """Write the payload unchanged unless the newest stored snapshot has identical bytes. Never overwrites."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    prev = latest_raw(spec)
    if prev and prev[1]["sha256"] == sha:
        return prev[0], prev[1], False
    stamp = datetime.now(timezone.utc)
    d = _slug(spec) / stamp.strftime("%Y%m%dT%H%M%SZ")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{spec.source_series_id.replace('^', '_')}.json"
    path.write_bytes(data)
    man = {"file": path.name, "source": spec.source, "series_key": spec.key, "source_url": url,
           "fetched_at": stamp.isoformat(), "bytes": len(data), "sha256": sha}
    (d / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    return path, man, True


def load_raw(path: Path, man: dict):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != man["sha256"]:
        raise ValueError(f"{path} does not match its manifest sha256 (file modified?)")
    return json.loads(data)


# ------------------------------------------------------------------ database
def _upsert(session, spec: SeriesSpec, obs: list[Observation], rep: MarketReport, man: dict, res: SeriesResult) -> None:
    now = datetime.now(timezone.utc)
    s = session.scalar(select(MarketSeries).where(MarketSeries.series_key == spec.key))
    meta = dict(source=spec.source, source_series_id=spec.source_series_id, name=spec.name, category=spec.category,
                unit=spec.unit, frequency=spec.frequency, source_url=man["source_url"],
                source_note=SOURCE_NOTES.get(spec.source), raw_file_sha256=man["sha256"], fetched_at=now,
                first_date=obs[0].obs_date if obs else None, last_date=obs[-1].obs_date if obs else None,
                n_observations=len(obs), quality_report=rep.to_dict())
    if s is None:
        session.add(MarketSeries(series_key=spec.key, **meta))
    else:
        for k, v in meta.items():
            setattr(s, k, v)
    session.flush()

    existing = {d: (id_, tuple(v)) for id_, d, *v in session.execute(
        select(MarketObservation.id, MarketObservation.obs_date, *[getattr(MarketObservation, f) for f in _FIELDS])
        .where(MarketObservation.series_key == spec.key))}
    new_rows, changed = [], []
    for o in obs:
        vals = tuple(getattr(o, f) for f in _FIELDS)
        old = existing.get(o.obs_date)
        if old is None:
            new_rows.append({"series_key": spec.key, "obs_date": o.obs_date, **dict(zip(_FIELDS, vals))})
        elif old[1] != vals:
            changed.append({"id": old[0], **dict(zip(_FIELDS, vals))})
        else:
            res.unchanged += 1
    if new_rows:
        session.bulk_insert_mappings(MarketObservation, new_rows)
    for row in changed:
        session.execute(update(MarketObservation).where(MarketObservation.id == row["id"]).values(
            **{k: v for k, v in row.items() if k != "id"}))
    res.inserted, res.updated = len(new_rows), len(changed)


def run_market_ingest(*, specs: Iterable[SeriesSpec] = SERIES, dry_run: bool = False, from_raw: bool = False,
                      session_factory: Callable | None = None, client: httpx.Client | None = None) -> MarketSummary:
    summary = MarketSummary(dry_run=dry_run)
    session = None
    if not dry_run:
        from app.historical.database import get_engine, get_sessionmaker
        from app.historical.models import HistoricalBase
        if session_factory is None:
            HistoricalBase.metadata.create_all(get_engine())
            session_factory = get_sessionmaker()
        session = session_factory()
    own_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    try:
        for spec in specs:
            res = SeriesResult(key=spec.key)
            summary.results.append(res)
            try:
                if from_raw:
                    prev = latest_raw(spec)
                    if prev is None:
                        raise FileNotFoundError("no stored raw snapshot (run without --from-raw first)")
                    path, man, payload, res.fetch = prev[0], prev[1], load_raw(*prev), "from_raw"
                else:
                    payload, url = fetcher.fetch(spec, client)
                    if dry_run:
                        man, res.fetch = {"source_url": url, "sha256": hashlib.sha256(
                            json.dumps(payload, sort_keys=True).encode()).hexdigest()}, "downloaded (not stored)"
                    else:
                        path, man, new = store_raw(spec, payload, url)
                        res.fetch = "downloaded" if new else "raw_reused"
                obs, res.report = clean(spec, payload)
                if not obs:
                    raise ValueError("no valid observations after cleaning")
                if dry_run:
                    res.status = "dry_run"
                    continue
                with session.begin_nested():
                    _upsert(session, spec, obs, res.report, man, res)
                session.commit()
            except Exception as e:                                  # noqa: BLE001  (reported, never hidden)
                if session is not None:
                    session.rollback()
                res.status, res.error = "error", f"{type(e).__name__}: {str(e)[:200]}"
                log.error("%s failed: %s", spec.key, res.error)
    finally:
        if session is not None:
            session.close()
        if own_client:
            client.close()
    return summary
