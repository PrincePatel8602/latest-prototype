"""Validation + cleaning of raw IBTrACS rows.

Nothing is dropped silently: every rejected row gets a reason, every repaired/blanked value
gets a quality flag, and everything is counted in the QualityReport.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.historical.categories import (
    CATEGORY_SOURCE_USA_WIND, CATEGORY_SOURCE_WMO_WIND, category_from_wind_kt,
)

MISSING_TOKENS = {"", "na", "nan", "null", "none", "-999", "-99", "-9999", "-999.0", "-99.0"}
ACCEPTED_TRACK_TYPES = {"main", "provisional"}
UNNAMED_TOKENS = {"", "UNNAMED", "NOT_NAMED", "NOT NAMED", "NONAME"}

WIND_RANGE_KT = (1.0, 250.0)        # physically plausible sustained wind (kt)
PRESSURE_RANGE_MB = (850.0, 1090.0)  # plausible central pressure (mb)
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


@dataclass(slots=True)
class TrackPoint:
    storm_id: str
    season: int
    number: int | None
    basin: str
    subbasin: str | None
    name: str
    timestamp: datetime
    nature: str | None
    lat: float
    lon: float
    wind_kt: float | None
    wind_source: str | None
    pressure_mb: float | None
    pressure_source: str | None
    original_category: int | None      # USA_SSHS exactly as published (None only if missing)
    normalized_category: int | None
    category_source: str | None
    track_type: str
    iflag: str | None
    is_interpolated: bool
    dist2land_km: float | None
    landfall_km: float | None
    quality_flags: tuple[str, ...]
    source_line: int


@dataclass
class QualityReport:
    source: str = ""
    version: str = ""
    subset: str = ""
    raw_rows: int = 0
    filtered_out_min_year: int = 0
    filtered_out_basin: int = 0
    valid_points: int = 0
    rejected_rows: int = 0
    duplicates_removed: int = 0
    duplicates_conflicting: int = 0
    reject_reasons: Counter = field(default_factory=Counter)
    flag_counts: Counter = field(default_factory=Counter)
    missing_wind: int = 0
    missing_pressure: int = 0
    missing_names: int = 0
    category_disagreements: int = 0
    storms: int = 0
    reject_samples: list[dict] = field(default_factory=list)

    def reject(self, line: int, sid: str, reason: str, detail: str = "") -> None:
        self.rejected_rows += 1
        self.reject_reasons[reason] += 1
        if len(self.reject_samples) < 200:
            self.reject_samples.append({"line": line, "sid": sid, "reason": reason, "detail": detail})

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("reject_reasons", "flag_counts")}
        d["reject_reasons"] = dict(self.reject_reasons)
        d["flag_counts"] = dict(self.flag_counts)
        return d


# ---------------------------------------------------------------- field parsers
def clean_str(v: str | None) -> str:
    return " ".join((v or "").split())


def parse_float(v: str | None) -> float | None:
    s = clean_str(v)
    if s.lower() in MISSING_TOKENS:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse_int(v: str | None) -> int | None:
    x = parse_float(v)
    return None if x is None else int(round(x))


def parse_time(v: str | None) -> datetime | None:
    s = clean_str(v)
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _ranged(value: float | None, lo: float, hi: float) -> tuple[float | None, bool]:
    """-> (value or None, was_out_of_range)"""
    if value is None:
        return None, False
    if lo <= value <= hi:
        return value, False
    return None, True


# ---------------------------------------------------------------- main entry
def clean_rows(
    rows: Iterable[tuple[int, dict[str, str]]],
    *,
    min_year: int | None = None,
    basins: Iterable[str] | None = None,
    now: datetime | None = None,
    report: QualityReport | None = None,
) -> tuple[list[TrackPoint], QualityReport]:
    report = report or QualityReport()
    basin_set = {b.strip().upper() for b in basins} if basins else None
    now = now or datetime.now(timezone.utc)
    latest_ok = now + timedelta(days=2)
    kept: dict[tuple[str, datetime], TrackPoint] = {}

    for line, r in rows:
        report.raw_rows += 1
        flags: list[str] = []
        sid = clean_str(r.get("SID"))
        if not sid:
            report.reject(line, "", "missing_storm_id")
            continue

        if basin_set is not None and clean_str(r.get("BASIN")).upper() not in basin_set:
            report.filtered_out_basin += 1
            continue

        season = parse_int(r.get("SEASON"))
        if season is None:
            if len(sid) >= 4 and sid[:4].isdigit():
                season = int(sid[:4]); flags.append("season_from_sid")
            else:
                report.reject(line, sid, "invalid_season", clean_str(r.get("SEASON")))
                continue
        if min_year is not None and season < min_year:
            report.filtered_out_min_year += 1
            continue

        ts = parse_time(r.get("ISO_TIME"))
        if ts is None:
            report.reject(line, sid, "invalid_timestamp", clean_str(r.get("ISO_TIME")))
            continue
        if ts > latest_ok:
            report.reject(line, sid, "future_timestamp", ts.isoformat())
            continue

        lat, lon = parse_float(r.get("LAT")), parse_float(r.get("LON"))
        if lat is None or lon is None:
            report.reject(line, sid, "missing_coordinates", f"{r.get('LAT')!r},{r.get('LON')!r}")
            continue
        if 180 < lon <= 360:
            lon -= 360; flags.append("lon_wrapped")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            report.reject(line, sid, "coordinates_out_of_range", f"{lat},{lon}")
            continue

        track_type = clean_str(r.get("TRACK_TYPE")) or "main"
        if not clean_str(r.get("TRACK_TYPE")):
            flags.append("track_type_missing")
        if track_type.lower() not in ACCEPTED_TRACK_TYPES:
            report.reject(line, sid, "non_main_track_type", track_type)
            continue

        # ---- wind (knots, 1-minute sustained): USA_WIND first, WMO_WIND as labelled fallback
        wind, wind_src = None, None
        for col in ("USA_WIND", "WMO_WIND"):
            raw_v = parse_float(r.get(col))
            v, bad = _ranged(raw_v, *WIND_RANGE_KT)
            if bad:
                flags.append(f"wind_out_of_range:{col}")
            if v is not None:
                wind, wind_src = v, col.lower()
                break

        pres, pres_src = None, None
        for col in ("USA_PRES", "WMO_PRES"):
            raw_v = parse_float(r.get(col))
            v, bad = _ranged(raw_v, *PRESSURE_RANGE_MB)
            if bad:
                flags.append(f"pressure_out_of_range:{col}")
            if v is not None:
                pres, pres_src = v, col.lower()
                break

        # ---- category: original preserved, normalised derived
        original = parse_int(r.get("USA_SSHS"))
        if original is not None and not (-5 <= original <= 5):
            flags.append("sshs_unexpected_value")
        normalized = category_from_wind_kt(wind)
        cat_source = None
        if normalized is not None:
            cat_source = CATEGORY_SOURCE_USA_WIND if wind_src == "usa_wind" else CATEGORY_SOURCE_WMO_WIND
        if original is not None and normalized is not None and original >= -1 and original != normalized:
            flags.append("category_disagrees_with_source")
            report.category_disagreements += 1

        name_raw = clean_str(r.get("NAME"))
        if name_raw == "":
            flags.append("name_missing")
        name = "UNNAMED" if name_raw.upper() in UNNAMED_TOKENS else name_raw.upper()

        iflag = clean_str(r.get("IFLAG")) or None
        if iflag is None:
            flags.append("iflag_missing")
        interpolated = bool(iflag) and iflag[0] == "I"

        d2l = parse_float(r.get("DIST2LAND"))
        lf = parse_float(r.get("LANDFALL"))
        if d2l is not None and d2l < 0:
            d2l = None; flags.append("dist2land_negative")
        if lf is not None and lf < 0:
            lf = None; flags.append("landfall_negative")

        point = TrackPoint(
            storm_id=sid, season=season, number=parse_int(r.get("NUMBER")),
            basin=clean_str(r.get("BASIN")).upper() or "UNK",
            subbasin=clean_str(r.get("SUBBASIN")).upper() or None,
            name=name, timestamp=ts, nature=clean_str(r.get("NATURE")).upper() or None,
            lat=lat, lon=lon, wind_kt=wind, wind_source=wind_src,
            pressure_mb=pres, pressure_source=pres_src,
            original_category=original, normalized_category=normalized, category_source=cat_source,
            track_type=track_type, iflag=iflag, is_interpolated=interpolated,
            dist2land_km=d2l, landfall_km=lf, quality_flags=tuple(flags), source_line=line,
        )

        key = (sid, ts)
        prev = kept.get(key)
        if prev is None:
            kept[key] = point
        else:
            report.duplicates_removed += 1
            same = (prev.lat, prev.lon, prev.wind_kt, prev.pressure_mb) == (lat, lon, wind, pres)
            if not same:
                report.duplicates_conflicting += 1
            # prefer an original observation over an interpolated one; otherwise keep the first
            if prev.is_interpolated and not point.is_interpolated:
                kept[key] = point

    points = sorted(kept.values(), key=lambda p: (p.storm_id, p.timestamp))
    report.valid_points = len(points)
    # counted on the FINAL (deduplicated) points so every number reconciles with valid_points
    report.missing_wind = sum(1 for p in points if p.wind_kt is None)
    report.missing_pressure = sum(1 for p in points if p.pressure_mb is None)
    report.missing_names = sum(1 for p in points if "name_missing" in p.quality_flags)
    for p in points:
        for f in p.quality_flags:
            report.flag_counts[f] += 1
    report.storms = len({p.storm_id for p in points})
    return points, report
