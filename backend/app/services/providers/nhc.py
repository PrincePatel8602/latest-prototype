"""Weather adapter: NOAA National Hurricane Center (public, NO API key needed).

Feed: https://www.nhc.noaa.gov/CurrentStorms.json  -> {"activeStorms": [ ... ]}
Per storm we read: id, name, classification (HU/TS/TD/...), intensity (knots, as a
string), latitudeNumeric / longitudeNumeric, movementDir, lastUpdate.

LIMITATION: this feed gives the CURRENT position only. The forecast track is
published as GIS files, which we do not parse yet. The UI says so.
An empty "activeStorms" list is normal outside storm season - it is NOT an error.
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.providers.base import ProviderError, get_json

log = logging.getLogger("finsight.providers.nhc")

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
KNOTS_TO_MPH = 1.15078

_CLASS_LABELS = {
    "HU": "Hurricane", "TS": "Tropical Storm", "TD": "Tropical Depression",
    "STS": "Subtropical Storm", "STD": "Subtropical Depression",
    "PTC": "Potential Tropical Cyclone", "PC": "Post-Tropical Cyclone",
}


@dataclass(frozen=True)
class RawStorm:
    id: str
    name: str
    label: str            # e.g. "Hurricane"
    basin: str            # "atlantic" | "east_pacific" | "central_pacific"
    knots: int
    lat: float
    lon: float            # negative = west
    last_update: datetime | None
    # Optional extras the feed carries for some storms. None = not supplied.
    movement_dir_deg: int | None = None     # direction the storm moves TOWARD, degrees
    movement_speed_kt: float | None = None
    pressure_mb: int | None = None


def category_from_knots(knots: int) -> int:
    """Saffir-Simpson category from 1-minute sustained wind in KNOTS (NHC thresholds).
    0 means 'below hurricane strength'."""
    if knots >= 137: return 5
    if knots >= 113: return 4
    if knots >= 96: return 3
    if knots >= 83: return 2
    if knots >= 64: return 1
    return 0


def wind_mph(knots: int) -> int:
    return round(knots * KNOTS_TO_MPH)


def classify_region(lat: float, lon: float, basin: str) -> str:
    """Rough bounding boxes - good enough to decide 'is this the Gulf?'."""
    if basin == "east_pacific":
        return "Eastern Pacific"
    if basin == "central_pacific":
        return "Central Pacific"
    if 18 <= lat <= 31 and -98 <= lon <= -80.5:
        return "Gulf of Mexico"
    if 8 <= lat <= 23 and -88 <= lon <= -59:
        return "Caribbean Sea"
    return "Atlantic Ocean"


def _number(v: Any) -> float | None:
    """float(v), or None if missing/garbage. NaN and infinity count as garbage."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Always timezone-aware, so timestamps can be compared with each other.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_storms(raw: Any) -> list[RawStorm]:
    """Pure function: NHC JSON -> list of storms.

    Wrong overall shape raises ProviderError. A single malformed storm entry
    (missing/invalid position or wind, impossible coordinates) is skipped, not fatal.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("activeStorms"), list):
        raise ProviderError("unexpected response shape")

    storms: list[RawStorm] = []
    skipped = 0
    for s in raw["activeStorms"]:
        if not isinstance(s, dict):
            skipped += 1
            continue
        lat, lon = _number(s.get("latitudeNumeric")), _number(s.get("longitudeNumeric"))
        knots = _number(s.get("intensity"))
        valid = (
            lat is not None and lon is not None and knots is not None
            and -90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= knots <= 300
        )
        if not valid:
            skipped += 1
            continue
        storm_id = str(s.get("id") or "").lower()
        basin = ("east_pacific" if storm_id.startswith("ep")
                 else "central_pacific" if storm_id.startswith("cp") else "atlantic")
        direction = _number(s.get("movementDir"))
        speed = _number(s.get("movementSpeed"))
        pressure = _number(s.get("pressure"))
        storms.append(RawStorm(
            id=storm_id or f"storm-{len(storms)}",
            name=str(s.get("name") or "Unnamed"),
            label=_CLASS_LABELS.get(str(s.get("classification") or "").upper(), "Tropical Cyclone"),
            basin=basin, knots=int(knots), lat=lat, lon=lon,  # type: ignore[arg-type]
            last_update=_parse_time(s.get("lastUpdate")),
            movement_dir_deg=int(direction) % 360 if direction is not None else None,
            movement_speed_kt=speed if speed is not None and speed >= 0 else None,
            pressure_mb=int(pressure) if pressure is not None and 800 <= pressure <= 1100 else None,
        ))
    if skipped:
        log.warning("NHC feed: skipped %d malformed storm entr%s", skipped, "y" if skipped == 1 else "ies")
    return storms


def fetch_storms() -> list[RawStorm]:
    return parse_storms(get_json(CURRENT_STORMS_URL))
