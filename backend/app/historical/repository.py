"""PostgreSQL access: idempotent upserts, structured filtering, serialisation with provenance."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.historical.categories import event_type_from_category, kt_to_mph
from app.historical.filters import StormFilter, storm_matches  # noqa: F401  (re-exported)
from app.historical.events import SourceProvenance, event_id_for
from app.historical.ibtracs.aggregate import StormSummary
from app.historical.ibtracs.clean import TrackPoint
from app.historical.models import HistoricalStorm, IngestionRun, StormTrackPoint

S = HistoricalStorm


# ------------------------------------------------------------------ filters (definition lives in filters.py)


def _cat_col(f: StormFilter):
    return S.max_category_in_gulf if f.category_scope == "gulf" else S.max_category_normalized


def apply_filter(stmt, f: StormFilter):
    if f.storm_id:
        stmt = stmt.where(S.storm_id == f.storm_id.strip())
    if f.name:
        stmt = stmt.where(S.name == f.name.strip().upper())
    if f.basin:
        stmt = stmt.where(S.basin == f.basin.strip().upper())
    if f.year is not None:
        stmt = stmt.where(S.year == f.year)
    if f.year_from is not None:
        stmt = stmt.where(S.year >= f.year_from)
    if f.year_to is not None:
        stmt = stmt.where(S.year <= f.year_to)
    if f.event_type:
        stmt = stmt.where(S.event_type == f.event_type)
    if f.gulf_only:
        stmt = stmt.where(S.gulf_of_mexico_entered.is_(True))
    if f.min_category is not None:
        stmt = stmt.where(_cat_col(f) >= f.min_category)
    if f.max_category is not None:
        stmt = stmt.where(_cat_col(f) <= f.max_category)
    if f.min_wind_kt is not None:
        stmt = stmt.where(S.max_wind_kt >= f.min_wind_kt)
    return stmt


# ------------------------------------------------------------------ writes
def _storm_values(s: StormSummary, prov: SourceProvenance, now: datetime) -> dict:
    return dict(
        storm_id=s.storm_id, name=s.name, year=s.year, number=s.number, basin=s.basin, subbasin=s.subbasin,
        region=s.region, event_type=event_type_from_category(s.max_category_normalized),
        start_datetime=s.start_datetime, end_datetime=s.end_datetime, duration_hours=s.duration_hours,
        max_wind_kt=s.max_wind_kt, min_pressure_mb=s.min_pressure_mb,
        max_category_normalized=s.max_category_normalized, max_category_original=s.max_category_original,
        category_source=s.category_source, track_length_km=s.track_length_km,
        n_observations=s.n_observations, n_original_observations=s.n_original_observations,
        gulf_of_mexico_entered=s.gulf_of_mexico_entered, gulf_observations=s.gulf_observations,
        max_category_in_gulf=s.max_category_in_gulf, max_wind_in_gulf_kt=s.max_wind_in_gulf_kt,
        landfall_indicator_observations=s.landfall_indicator_observations, min_dist2land_km=s.min_dist2land_km,
        min_lat=s.min_lat, max_lat=s.max_lat, min_lon=s.min_lon, max_lon=s.max_lon,
        source=prov.source, source_version=prov.source_version, source_url=prov.source_url,
        source_subset=prov.subset, source_downloaded_at=prov.downloaded_at, source_file_sha256=prov.file_sha256,
        ingestion_timestamp=now, data_quality_status=s.data_quality_status,
        quality_flags=s.quality_flags or None, content_hash=s.content_hash,
    )


def _point_values(p: TrackPoint, prov: SourceProvenance) -> dict:
    return dict(
        storm_id=p.storm_id, timestamp=p.timestamp, latitude=p.lat, longitude=p.lon,
        wind_kt=p.wind_kt, wind_source=p.wind_source, pressure_mb=p.pressure_mb,
        pressure_source=p.pressure_source, original_category=p.original_category,
        normalized_category=p.normalized_category, category_source=p.category_source, nature=p.nature,
        track_type=p.track_type, iflag=p.iflag, is_interpolated=p.is_interpolated,
        dist2land_km=p.dist2land_km, landfall_km=p.landfall_km,
        quality_flags=";".join(p.quality_flags) or None, source=prov.source, source_version=prov.source_version,
    )


def upsert_storm(session: Session, summary: StormSummary, points: list[TrackPoint], prov: SourceProvenance,
                 *, force: bool = False, now: datetime | None = None) -> tuple[str, HistoricalStorm]:
    """Insert/update one storm and its track points atomically.

    Returns ("inserted" | "updated" | "skipped", row). Identity = storm_id (unique); change
    detection = content_hash, so re-running the same ingestion creates no duplicates and no writes.
    """
    now = now or datetime.now(timezone.utc)
    existing = session.scalar(select(S).where(S.storm_id == summary.storm_id))
    if existing is not None and existing.content_hash == summary.content_hash and not force:
        return "skipped", existing

    values = _storm_values(summary, prov, now)
    if existing is None:
        row = S(**values)
        session.add(row)
        session.flush()
        action = "inserted"
    else:
        for k, v in values.items():
            setattr(existing, k, v)
        session.execute(delete(StormTrackPoint).where(StormTrackPoint.storm_id == existing.storm_id))
        session.flush()
        row, action = existing, "updated"

    if points:
        session.execute(insert(StormTrackPoint), [_point_values(p, prov) for p in points])
    session.flush()
    return action, row


def stored_hashes(session: Session) -> dict[str, str]:
    """storm_id -> content_hash for every stored storm (change detection in a single query)."""
    return {sid: h for sid, h in session.execute(select(S.storm_id, S.content_hash))}


def mark_pinecone_synced(session: Session, rows: list[HistoricalStorm], namespace: str, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    for r in rows:
        r.pinecone_record_id = event_id_for(r.storm_id)
        r.pinecone_namespace = namespace
        r.pinecone_synced_hash = r.content_hash
        r.pinecone_synced_at = now


def storms_needing_pinecone_sync(session: Session, storm_ids: list[str], force: bool = False) -> list[HistoricalStorm]:
    if not storm_ids:
        return []
    rows = session.scalars(select(S).where(S.storm_id.in_(storm_ids))).all()
    return [r for r in rows if force or r.pinecone_synced_hash != r.content_hash]


def record_run(session: Session, run: IngestionRun) -> IngestionRun:
    session.add(run)
    session.flush()
    return run


# ------------------------------------------------------------------ reads
def query_storms(session: Session, f: StormFilter, *, limit: int = 50, offset: int = 0) -> list[HistoricalStorm]:
    stmt = apply_filter(select(S), f).order_by(
        S.max_category_normalized.desc().nulls_last(), S.max_wind_kt.desc().nulls_last(), S.year.desc(), S.storm_id)
    return list(session.scalars(stmt.limit(limit).offset(offset)).all())


def count_storms(session: Session, f: StormFilter | None = None) -> int:
    stmt = select(func.count()).select_from(S)
    return session.scalar(apply_filter(stmt, f) if f else stmt) or 0


def get_storm(session: Session, storm_id: str) -> HistoricalStorm | None:
    return session.scalar(select(S).where(S.storm_id == storm_id))


def get_storms_by_ids(session: Session, storm_ids: list[str]) -> dict[str, HistoricalStorm]:
    if not storm_ids:
        return {}
    return {r.storm_id: r for r in session.scalars(select(S).where(S.storm_id.in_(storm_ids))).all()}


def get_track(session: Session, storm_id: str) -> list[StormTrackPoint]:
    return list(session.scalars(select(StormTrackPoint).where(StormTrackPoint.storm_id == storm_id)
                                .order_by(StormTrackPoint.timestamp)).all())


def category_distribution(session: Session, f: StormFilter | None = None) -> dict[str, int]:
    """Counts per peak category (deterministic analytics building block)."""
    stmt = select(S.max_category_normalized, func.count()).select_from(S)
    if f:
        stmt = apply_filter(stmt, f)
    rows = session.execute(stmt.group_by(S.max_category_normalized)).all()
    return {("unknown" if c is None else str(c)): n for c, n in sorted(rows, key=lambda r: (r[0] is None, r[0]))}


def duration_stats(session: Session, f: StormFilter | None = None) -> dict:
    stmt = select(func.count(), func.min(S.duration_hours), func.avg(S.duration_hours), func.max(S.duration_hours)).select_from(S)
    if f:
        stmt = apply_filter(stmt, f)
    n, lo, avg, hi = session.execute(stmt).one()
    return {"storms": n, "duration_hours_min": lo, "duration_hours_avg": None if avg is None else round(float(avg), 1),
            "duration_hours_max": hi}


def latest_run(session: Session) -> IngestionRun | None:
    return session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))


# ------------------------------------------------------------------ serialisation
def provenance_of(row: HistoricalStorm) -> dict:
    return {
        "source": row.source, "dataset_version": row.source_version, "source_url": row.source_url,
        "subset": row.source_subset, "downloaded_at": row.source_downloaded_at,
        "raw_file_sha256": row.source_file_sha256, "source_record_id": row.storm_id,
        "ingested_at": row.ingestion_timestamp.isoformat() if row.ingestion_timestamp else None,
        "data_quality_status": row.data_quality_status,
        "postgres": {"table": "historical_storms", "id": row.id},
        "pinecone": ({"namespace": row.pinecone_namespace, "record_id": row.pinecone_record_id,
                      "in_sync": row.pinecone_synced_hash == row.content_hash}
                     if row.pinecone_record_id else None),
    }


def storm_to_dict(row: HistoricalStorm) -> dict:
    return {
        "postgres_id": row.id, "event_id": event_id_for(row.storm_id), "storm_id": row.storm_id,
        "name": row.name, "year": row.year, "basin": row.basin, "region": row.region,
        "event_type": row.event_type,
        "start_datetime": row.start_datetime.isoformat(), "end_datetime": row.end_datetime.isoformat(),
        "duration_hours": row.duration_hours,
        "max_wind_kt": row.max_wind_kt, "max_wind_mph": kt_to_mph(row.max_wind_kt),
        "min_pressure_mb": row.min_pressure_mb,
        "max_category_normalized": row.max_category_normalized, "max_category_original": row.max_category_original,
        "category_source": row.category_source, "track_length_km": row.track_length_km,
        "n_observations": row.n_observations, "gulf_of_mexico_entered": row.gulf_of_mexico_entered,
        "max_category_in_gulf": row.max_category_in_gulf,
        "landfall_indicator_observations": row.landfall_indicator_observations,
        "data_quality_status": row.data_quality_status, "quality_flags": row.quality_flags or {},
        "provenance": provenance_of(row),
    }


def track_point_to_dict(p: StormTrackPoint) -> dict:
    return {"timestamp": p.timestamp.isoformat(), "latitude": p.latitude, "longitude": p.longitude,
            "wind_kt": p.wind_kt, "pressure_mb": p.pressure_mb, "original_category": p.original_category,
            "normalized_category": p.normalized_category, "category_source": p.category_source,
            "is_interpolated": p.is_interpolated, "nature": p.nature, "quality_flags": p.quality_flags}
