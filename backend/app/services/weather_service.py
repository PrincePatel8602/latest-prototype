"""Weather service: turns provider data (or the demo scenario) into WeatherEvents.

Provider-specific parsing lives in providers/nhc.py. The decision of WHICH
event matches a user's question lives in agents/weather_agent.py.
"""
import logging

from pydantic import ValidationError

from app.schemas.common import DataMeta
from app.schemas.weather import ForecastPoint, Severity, WeatherEvent, WeatherResponse
from app.services.common import now_utc, resolve
from app.services.providers import nhc
from app.services.providers.base import ProviderError

log = logging.getLogger("finsight.services.weather")

LIVE_SOURCE = "NOAA National Hurricane Center (CurrentStorms.json)"
DEMO_SOURCE = "Built-in demo scenario (fictional storm, not a real forecast)"


def severity_from_category(category: int) -> Severity:
    """Simple documented rule: Cat 0 low, 1-2 moderate, 3-4 high, 5 extreme."""
    if category <= 0:
        return "LOW"
    if category <= 2:
        return "MODERATE"
    return "HIGH" if category <= 4 else "EXTREME"


# Backwards-compatible private alias (kept so existing imports keep working).
_severity_from_category = severity_from_category

# Shared by demo + live. RULE-BASED ASSUMPTION (not observed data): a storm
# inside the Gulf of Mexico is treated as a threat to Gulf energy infrastructure.
_GULF_REGIONS = ["Offshore Gulf of Mexico", "Louisiana coast", "Texas Gulf Coast"]
_GULF_INFRA = [
    "Offshore oil & gas platforms",
    "Gulf Coast refineries",
    "LNG export terminals",
    "Ports & pipelines",
]

# DEMO SCENARIO - a fictional storm, not a real forecast. Fully deterministic.
# 130 mph sustained wind is Saffir-Simpson Category 4 (130-156 mph).
_DEMO_EVENT = WeatherEvent(
    id="demo-gulf-hurricane",
    event_type="hurricane",
    name="Demo Hurricane (scenario)",
    category=4,
    wind_mph=130,
    region="Gulf of Mexico",
    lat=25.5,
    lon=-90.0,
    forecast_path=[
        ForecastPoint(hours_ahead=0, lat=25.5, lon=-90.0, wind_mph=130),
        ForecastPoint(hours_ahead=24, lat=27.2, lon=-91.0, wind_mph=135),
        ForecastPoint(hours_ahead=48, lat=29.0, lon=-91.5, wind_mph=125),
        ForecastPoint(hours_ahead=72, lat=31.0, lon=-91.0, wind_mph=70),
    ],
    affected_regions=_GULF_REGIONS,
    affected_infrastructure=_GULF_INFRA,
    affected_sectors=["Energy"],
    severity=severity_from_category(4),
    forecast_available=True,   # illustrative scenario track, labeled DEMO everywhere
    data_source=DEMO_SOURCE,
    movement_dir_deg=340,      # moving north-north-west, consistent with the path above
    movement_speed_mph=12,
    pressure_mb=935,
)


def _demo(meta: DataMeta) -> WeatherResponse:
    notice = meta.notice or ""
    meta = meta.model_copy(update={
        "notice": (notice + " " if notice else "") + "Event is a fictional scenario; its forecast path is illustrative.",
    })
    return WeatherResponse(meta=meta, events=[_DEMO_EVENT])


def _to_event(s: nhc.RawStorm) -> WeatherEvent:
    category = nhc.category_from_knots(s.knots)
    region = nhc.classify_region(s.lat, s.lon, s.basin)
    in_gulf = region == "Gulf of Mexico"
    mph = nhc.wind_mph(s.knots)
    return WeatherEvent(
        id=s.id,
        event_type="hurricane" if category >= 1 else "tropical_storm",
        name=f"{s.label} {s.name}",
        category=category,
        wind_mph=mph,
        region=region,
        lat=s.lat,
        lon=s.lon,
        # The NHC feed gives the current position only (see providers/nhc.py).
        # We do NOT invent a track: this single point is "now".
        forecast_path=[ForecastPoint(hours_ahead=0, lat=s.lat, lon=s.lon, wind_mph=mph)],
        affected_regions=_GULF_REGIONS if in_gulf else [],
        affected_infrastructure=_GULF_INFRA if in_gulf else [],
        affected_sectors=["Energy"] if in_gulf else [],
        severity=severity_from_category(category),
        forecast_available=False,
        data_source=LIVE_SOURCE,
        last_update=s.last_update,
        movement_dir_deg=s.movement_dir_deg,
        movement_speed_mph=round(s.movement_speed_kt * nhc.KNOTS_TO_MPH) if s.movement_speed_kt is not None else None,
        pressure_mb=s.pressure_mb,
    )


def _live() -> WeatherResponse:
    storms = nhc.fetch_storms()  # raises ProviderError on timeout / HTTP error / bad shape
    try:
        events = [_to_event(s) for s in storms]
    except (ValueError, TypeError, OverflowError, ValidationError) as e:
        # Parsed JSON that still produces an impossible event = malformed provider data.
        log.warning("NHC data could not be converted to events: %s", type(e).__name__)
        raise ProviderError("malformed provider data") from None
    # An empty list is a REAL answer ("no storms right now"), not a failure.
    if events:
        notice = "Live NOAA NHC data. Current position only — forecast track not available from this feed."
    else:
        notice = "No active tropical cyclones reported by NOAA NHC. Turn on DEMO_MODE to see the demo hurricane scenario."
    stamps = [s.last_update for s in storms if s.last_update]
    meta = DataMeta(source="live", notice=notice, as_of=max(stamps) if stamps else now_utc())
    return WeatherResponse(meta=meta, events=events)


def get_weather() -> WeatherResponse:
    """Live NHC data when DEMO_MODE=false; otherwise (or on any provider failure) the demo scenario.

    NHC needs no API key, so there is no 'missing key' case for weather today;
    `resolve` already supports one (has_key=...) for a future keyed provider.
    """
    return resolve("weather", live=_live, demo=_demo, ttl_seconds=300)
