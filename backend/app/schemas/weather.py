from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import DataMeta
from app.schemas.portfolio import Sector
from app.schemas.query import ParsedQuery
from app.utils.text import clean_text

Severity = Literal["LOW", "MODERATE", "HIGH", "EXTREME"]


class ForecastPoint(BaseModel):
    hours_ahead: int
    lat: float
    lon: float
    wind_mph: int


class WeatherEvent(BaseModel):
    id: str
    event_type: Literal["hurricane", "tropical_storm"]
    name: str
    category: int  # Saffir-Simpson 1-5; 0 = below hurricane strength
    wind_mph: int
    region: str
    lat: float
    lon: float
    forecast_path: list[ForecastPoint]
    affected_regions: list[str]
    affected_infrastructure: list[str]
    affected_sectors: list[str]
    severity: Severity
    # --- Phase 6 additions (all optional/defaulted: existing clients keep working) ---
    # True ONLY if forecast_path contains points beyond "now" that a provider/scenario supplied.
    forecast_available: bool = False
    # Which feed produced this event, so a reader can always trace it.
    data_source: str = ""
    # When the PROVIDER last updated this storm (None for demo or if not supplied).
    last_update: datetime | None = None
    # Current motion as reported by the provider. None = not supplied (never guessed).
    movement_dir_deg: int | None = None
    movement_speed_mph: int | None = None
    pressure_mb: int | None = None


class WeatherResponse(BaseModel):
    """Response of GET /api/weather (shape unchanged; extra fields are additive)."""

    meta: DataMeta
    events: list[WeatherEvent]


# --------------------------------------------------------------------------
# Weather Agent contract
# --------------------------------------------------------------------------
class WeatherRequest(BaseModel):
    """What the Weather Agent was asked to look for (derived from a ParsedQuery)."""

    event_type: Literal["hurricane", "tropical_storm", "none"] = "none"
    event_category: int | None = Field(default=None, ge=1, le=5)
    region: str | None = None
    sectors: list[Sector] = []
    time_horizon: str | None = None
    time_horizon_days: int | None = None


MatchLevel = Literal["full", "partial", "none"]
WeatherStatus = Literal[
    "matched",            # at least one active event satisfies every stated criterion
    "partial_match",      # an event matches type + region, but not the requested category
    "no_match",           # active events exist, but none fit the request
    "no_active_events",   # the provider reports no active tropical cyclones
    "unsupported_event",  # the request is not about a hurricane / tropical storm
]


class EventMatch(BaseModel):
    """One active event, annotated with how well it fits the request."""

    event: WeatherEvent
    match: MatchLevel
    type_match: bool
    region_match: bool
    category_match: bool | None  # None = the request did not state a category


class WeatherIntelligence(BaseModel):
    """Structured output of the Weather Agent, consumed by later agents.

    It contains ONLY weather facts and rule-based geography/sector mapping.
    It deliberately contains no portfolio, risk or dollar-impact figures.
    """

    # None only when no provider was queried (status = "unsupported_event").
    meta: DataMeta | None
    status: WeatherStatus
    request: WeatherRequest
    events: list[EventMatch]           # every active event, annotated, best match first
    primary_event: WeatherEvent | None  # best matching event, or None
    # Derived from primary_event (empty when there is none):
    affected_regions: list[str] = []
    affected_infrastructure: list[str] = []
    affected_sectors: list[str] = []
    # affected_sectors narrowed to the sectors the user asked about (if they asked).
    relevant_sectors: list[str] = []
    severity: Severity | None = None
    forecast_available: bool = False
    summary: str
    warnings: list[str] = []


class WeatherAnalyzeIn(BaseModel):
    """Body of POST /api/weather/analyze: give a question OR an already-parsed query."""

    query: str | None = Field(default=None, min_length=3, max_length=500)
    parsed: ParsedQuery | None = None

    @field_validator("query")
    @classmethod
    def sanitize(cls, v: str | None) -> str | None:
        # Same sanitising as QueryIn, so both endpoints treat free text identically.
        if v is None:
            return None
        cleaned = clean_text(v, 500)
        if len(cleaned) < 3:
            raise ValueError("query is too short")
        return cleaned

    @model_validator(mode="after")
    def exactly_one(self) -> "WeatherAnalyzeIn":
        if (self.query is None) == (self.parsed is None):
            raise ValueError("provide exactly one of 'query' or 'parsed'")
        return self


class WeatherAgentResponse(BaseModel):
    query: str | None            # sanitised question, when one was supplied
    parsed: ParsedQuery
    parse_notice: str | None = None
    weather: WeatherIntelligence
