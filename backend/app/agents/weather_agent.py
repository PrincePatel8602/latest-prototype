"""Weather Agent.

RESPONSIBILITY: given the structured question from the Query Understanding
agent, find out whether an ACTIVE weather event matches it and return
structured weather intelligence for downstream agents.

INPUT : ParsedQuery (event type, category, region, sectors, time horizon).
OUTPUT: WeatherIntelligence (see schemas/weather.py).
TOOLS : weather_service.get_weather() - live NOAA NHC or the demo scenario.

DESIGN DECISIONS (the "why"):
* The agent never talks HTTP. Provider calls and fallbacks live in
  services/weather_service.py + providers/nhc.py; this file only decides what
  the data MEANS for the question. That keeps it unit-testable with fake data.
* Matching is explicit and explainable: each event gets type/region/category
  booleans, and the response says which criterion failed.
* Weather facts only. No portfolio, risk, dollar-impact or hedging output -
  those belong to later agents. Sector lists are the same rule-based geography
  mapping the service uses (Gulf storm -> Energy), not a market forecast.
* Honesty: no forecast is invented. If the provider gave none, we say so, and
  a requested time horizon is flagged as not coverable.
"""
from app.schemas.query import ParsedQuery
from app.schemas.weather import (
    EventMatch,
    MatchLevel,
    WeatherEvent,
    WeatherIntelligence,
    WeatherRequest,
    WeatherResponse,
)
from app.services import weather_service

_SUPPORTED_TYPES = {"hurricane", "tropical_storm"}

# A requested region -> the event.region values it covers. Matching also accepts
# the requested region appearing inside event.affected_regions (see _region_match).
_REGION_ALIASES: dict[str, set[str]] = {
    "gulf of mexico": {"gulf of mexico"},
    "gulf of america": {"gulf of mexico"},
    "gulf coast": {"gulf of mexico"},
    "texas": {"gulf of mexico"},
    "louisiana": {"gulf of mexico"},
    "caribbean sea": {"caribbean sea"},
    "caribbean": {"caribbean sea"},
    "atlantic ocean": {"atlantic ocean"},
    "atlantic": {"atlantic ocean"},
}


# --------------------------------------------------------------------------
# Step 1: understand what is being asked
# --------------------------------------------------------------------------
def build_request(parsed: ParsedQuery) -> WeatherRequest:
    """ParsedQuery -> WeatherRequest. Only storm event types are carried over."""
    event_type = parsed.event_type if parsed.event_type in _SUPPORTED_TYPES else "none"
    return WeatherRequest(
        event_type=event_type,  # type: ignore[arg-type]
        event_category=parsed.event_category,
        region=parsed.region,
        sectors=list(parsed.sectors),
        time_horizon=parsed.time_horizon,
        time_horizon_days=parsed.time_horizon_days,
    )


def is_supported(parsed: ParsedQuery) -> bool:
    """Weather Agent handles hurricane / tropical-storm questions (or ones naming no event)."""
    return parsed.supported and parsed.event_type in (_SUPPORTED_TYPES | {"none"})


# --------------------------------------------------------------------------
# Step 2: match active events against the request
# --------------------------------------------------------------------------
def _region_match(requested: str | None, event: WeatherEvent) -> bool:
    if not requested:
        return True  # no region stated -> not a constraint
    wanted = requested.strip().lower()
    if wanted in _REGION_ALIASES:
        if event.region.lower() in _REGION_ALIASES[wanted]:
            return True
    elif wanted == event.region.lower():
        return True
    return any(wanted in r.lower() for r in event.affected_regions)


def match_event(request: WeatherRequest, event: WeatherEvent) -> EventMatch:
    type_ok = request.event_type == "none" or request.event_type == event.event_type
    region_ok = _region_match(request.region, event)
    category_ok = None if request.event_category is None else event.category == request.event_category

    if type_ok and region_ok and category_ok is not False:
        level: MatchLevel = "full"
    elif type_ok and region_ok:
        level = "partial"  # right kind of storm in the right place, different strength
    else:
        level = "none"
    return EventMatch(event=event, match=level, type_match=type_ok, region_match=region_ok,
                      category_match=category_ok)


_RANK = {"full": 0, "partial": 1, "none": 2}


def match_events(request: WeatherRequest, events: list[WeatherEvent]) -> list[EventMatch]:
    """Annotate every event; best match first (then stronger storm first)."""
    matches = [match_event(request, e) for e in events]
    return sorted(matches, key=lambda m: (_RANK[m.match], -m.event.category, -m.event.wind_mph, m.event.id))


# --------------------------------------------------------------------------
# Step 3: assemble the result
# --------------------------------------------------------------------------
def _describe(request: WeatherRequest) -> str:
    kind = request.event_type.replace("_", " ") if request.event_type != "none" else "tropical cyclone"
    cat = f" Category {request.event_category}" if request.event_category else ""
    where = f" in {request.region}" if request.region else ""
    return f"{cat.strip() + ' ' if cat else ''}{kind}{where}".strip()


def _source_label(response: WeatherResponse) -> str:
    return "LIVE" if response.meta.source == "live" else "DEMO"


def _warnings(request: WeatherRequest, response: WeatherResponse, primary: WeatherEvent | None,
              status: str) -> list[str]:
    out: list[str] = []
    meta = response.meta
    if meta.source == "demo":
        out.append("DEMO DATA: this is a built-in fictional scenario, not an observed storm."
                   + (f" {meta.notice}" if meta.notice else ""))

    if status == "no_active_events":
        out.append("No active tropical cyclones are reported right now; the requested event is "
                   "hypothetical. Later agents must treat it as a scenario, not an observation.")
    elif status == "no_match":
        out.append(f"Active storms exist, but none match the request ({_describe(request)}).")
    elif status == "partial_match" and primary is not None and request.event_category is not None:
        out.append(f"Requested Category {request.event_category}, but the closest matching event is "
                   f"{'Category ' + str(primary.category) if primary.category else 'below hurricane strength'}.")

    if primary is not None:
        if not primary.forecast_available:
            out.append("Provider supplies current position only — no forecast track is available.")
        if request.time_horizon_days is not None:
            if not primary.forecast_available:
                out.append(f"Time horizon '{request.time_horizon}' cannot be assessed: no forecast data.")
            else:
                covered_h = max((p.hours_ahead for p in primary.forecast_path), default=0)
                if request.time_horizon_days * 24 > covered_h:
                    out.append(f"Time horizon '{request.time_horizon}' extends beyond the "
                               f"{covered_h}h of forecast available.")
        if request.sectors and not [s for s in primary.affected_sectors if s in request.sectors]:
            out.append("The matched event has no mapped impact on the requested sector(s): "
                       + ", ".join(request.sectors) + ".")
    return out


def analyze(request: WeatherRequest, response: WeatherResponse) -> WeatherIntelligence:
    """Pure function (no I/O): request + provider data -> intelligence. Easy to test."""
    matches = match_events(request, response.events)
    best = matches[0] if matches else None
    primary = best.event if best and best.match != "none" else None

    if not response.events:
        status = "no_active_events"
    elif best is not None and best.match == "full":
        status = "matched"
    elif best is not None and best.match == "partial":
        status = "partial_match"
    else:
        status = "no_match"

    relevant = ([s for s in primary.affected_sectors if s in request.sectors]
                if primary and request.sectors else list(primary.affected_sectors) if primary else [])

    label = _source_label(response)
    if primary is not None:
        cat = f"Category {primary.category}" if primary.category else "below hurricane strength"
        summary = (f"[{label}] {primary.name}: {cat}, {primary.wind_mph} mph, {primary.region} — "
                   f"severity {primary.severity}"
                   + (f"; affects {', '.join(primary.affected_sectors)}." if primary.affected_sectors
                      else "; no mapped sector impact."))
    elif status == "no_active_events":
        summary = f"[{label}] No active tropical cyclones; requested {_describe(request)} is hypothetical."
    else:
        summary = f"[{label}] No active event matches the requested {_describe(request)}."

    return WeatherIntelligence(
        meta=response.meta,
        status=status,  # type: ignore[arg-type]
        request=request,
        events=matches,
        primary_event=primary,
        affected_regions=list(primary.affected_regions) if primary else [],
        affected_infrastructure=list(primary.affected_infrastructure) if primary else [],
        affected_sectors=list(primary.affected_sectors) if primary else [],
        relevant_sectors=relevant,
        severity=primary.severity if primary else None,
        forecast_available=primary.forecast_available if primary else False,
        summary=summary,
        warnings=_warnings(request, response, primary, status),
    )


def _unsupported(parsed: ParsedQuery, request: WeatherRequest) -> WeatherIntelligence:
    reason = (f"Event type '{parsed.event_type}' is not supported by the Weather Agent — "
              "only hurricane / tropical-storm analysis is available.")
    return WeatherIntelligence(
        meta=None, status="unsupported_event", request=request, events=[], primary_event=None,
        summary=reason, warnings=[reason],
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def run_weather_agent(parsed: ParsedQuery) -> WeatherIntelligence:
    """Never raises for provider problems: get_weather() already falls back to labeled demo data."""
    request = build_request(parsed)
    if not is_supported(parsed):
        return _unsupported(parsed, request)  # no provider call is made
    return analyze(request, weather_service.get_weather())
