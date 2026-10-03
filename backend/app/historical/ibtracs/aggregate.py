"""Storm-level aggregation and deterministic derived features (pure Python, no LLM)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from app.historical.geo import GULF_POLYGON_NOTE, haversine_km, in_gulf
from app.historical.ibtracs.clean import TrackPoint

# Bump when aggregation/normalisation logic changes so a re-run updates stored rows.
PIPELINE_VERSION = "1"

BASIN_NAMES = {
    "NA": "North Atlantic", "EP": "Eastern North Pacific", "WP": "Western North Pacific",
    "NI": "North Indian", "SI": "South Indian", "SP": "South Pacific", "SA": "South Atlantic",
}


@dataclass
class StormSummary:
    storm_id: str
    name: str
    year: int
    number: int | None
    basin: str
    subbasin: str | None
    region: str
    start_datetime: datetime
    end_datetime: datetime
    duration_hours: float
    n_observations: int
    n_original_observations: int
    max_wind_kt: float | None
    min_pressure_mb: float | None
    max_category_normalized: int | None
    max_category_original: int | None
    category_source: str | None
    track_length_km: float | None
    gulf_of_mexico_entered: bool
    gulf_observations: int
    max_category_in_gulf: int | None
    max_wind_in_gulf_kt: float | None
    landfall_indicator_observations: int
    min_dist2land_km: float | None
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    data_quality_status: str
    quality_flags: dict = field(default_factory=dict)
    content_hash: str = ""
    notes: list[str] = field(default_factory=list)


def _region(basin: str, gulf: bool) -> str:
    base = BASIN_NAMES.get(basin, basin)
    return f"{base} / Gulf of Mexico" if gulf else base


def _max(values: Iterable):
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def _min(values: Iterable):
    vals = [v for v in values if v is not None]
    return min(vals) if vals else None


def summarize_storm(points: list[TrackPoint]) -> StormSummary:
    points = sorted(points, key=lambda p: p.timestamp)
    first, last = points[0], points[-1]
    original = [p for p in points if not p.is_interpolated]
    basis = original if original else points          # statistics use observed points when possible
    notes: list[str] = []
    if not original:
        notes.append("all points interpolated; statistics use interpolated points")

    name_counts = Counter(p.name for p in points if p.name != "UNNAMED")
    name = name_counts.most_common(1)[0][0] if name_counts else "UNNAMED"

    track_len = None
    if len(basis) >= 2:
        track_len = round(sum(haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(basis, basis[1:])), 1)

    gulf_pts = [p for p in basis if in_gulf(p.lat, p.lon)]
    flags = Counter(f for p in points for f in p.quality_flags)
    max_wind = _max(p.wind_kt for p in basis)
    min_pres = _min(p.pressure_mb for p in basis)

    if any(p.track_type.lower() == "provisional" for p in points):
        status = "provisional"
    elif max_wind is None:
        status = "incomplete"          # no usable wind at all
    elif min_pres is None:
        status = "partial"             # wind present, pressure never reported
    else:
        status = "ok"

    s = StormSummary(
        storm_id=first.storm_id, name=name, year=first.season, number=first.number,
        basin=first.basin, subbasin=first.subbasin, region=_region(first.basin, bool(gulf_pts)),
        start_datetime=first.timestamp, end_datetime=last.timestamp,
        duration_hours=round((last.timestamp - first.timestamp).total_seconds() / 3600, 1),
        n_observations=len(points), n_original_observations=len(original),
        max_wind_kt=max_wind, min_pressure_mb=min_pres,
        max_category_normalized=_max(p.normalized_category for p in basis),
        max_category_original=_max(p.original_category for p in basis),
        category_source=next((p.category_source for p in basis if p.normalized_category ==
                              _max(q.normalized_category for q in basis)), None),
        track_length_km=track_len,
        gulf_of_mexico_entered=bool(gulf_pts), gulf_observations=len(gulf_pts),
        max_category_in_gulf=_max(p.normalized_category for p in gulf_pts),
        max_wind_in_gulf_kt=_max(p.wind_kt for p in gulf_pts),
        landfall_indicator_observations=sum(1 for p in basis if p.landfall_km == 0),
        min_dist2land_km=_min(p.dist2land_km for p in basis),
        min_lat=min(p.lat for p in points), max_lat=max(p.lat for p in points),
        min_lon=min(p.lon for p in points), max_lon=max(p.lon for p in points),
        data_quality_status=status, quality_flags=dict(flags), notes=notes,
    )
    if s.gulf_of_mexico_entered:
        s.notes.append(f"Gulf flag uses an {GULF_POLYGON_NOTE}")
    s.content_hash = storm_content_hash(s, points)
    return s


def storm_content_hash(s: StormSummary, points: list[TrackPoint]) -> str:
    """Stable digest of everything we would store, plus pipeline/source version."""
    payload = {
        "pipeline": PIPELINE_VERSION,
        "summary": {k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in s.__dict__.items() if k not in ("content_hash", "notes")},
        "points": [(p.timestamp.isoformat(), p.lat, p.lon, p.wind_kt, p.pressure_mb,
                    p.original_category, p.normalized_category, p.is_interpolated, p.track_type,
                    p.nature, p.dist2land_km, p.landfall_km) for p in points],
    }
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def group_by_storm(points: Iterable[TrackPoint]) -> dict[str, list[TrackPoint]]:
    groups: dict[str, list[TrackPoint]] = defaultdict(list)
    for p in points:
        groups[p.storm_id].append(p)
    return groups


def summarize_all(points: Iterable[TrackPoint]) -> list[StormSummary]:
    return [summarize_storm(pts) for _, pts in sorted(group_by_storm(points).items())]
