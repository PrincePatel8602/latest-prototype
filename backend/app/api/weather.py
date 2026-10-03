from fastapi import APIRouter

from app.agents.query_understanding import understand_query
from app.agents.weather_agent import run_weather_agent
from app.schemas.weather import WeatherAgentResponse, WeatherAnalyzeIn, WeatherResponse
from app.services import weather_service

router = APIRouter(prefix="/api", tags=["weather"])


@router.get("/weather", response_model=WeatherResponse)
def read_weather() -> WeatherResponse:
    """Raw active events (live NOAA NHC or the demo scenario). Dashboard panel uses this."""
    return weather_service.get_weather()


@router.post("/weather/analyze", response_model=WeatherAgentResponse)
def analyze_weather(body: WeatherAnalyzeIn) -> WeatherAgentResponse:
    """Phase 6 Weather Agent: does an active event match the question?

    Send either a free-text `query` (it is parsed by the Query Understanding
    agent first) or an already-parsed `parsed` object (no second parse/LLM call).
    Returns weather intelligence only - no portfolio risk or financial impact.
    """
    if body.parsed is not None:
        return WeatherAgentResponse(query=None, parsed=body.parsed,
                                    weather=run_weather_agent(body.parsed))
    assert body.query is not None  # guaranteed by WeatherAnalyzeIn validation
    result = understand_query(body.query)
    return WeatherAgentResponse(query=result.query, parsed=result.parsed, parse_notice=result.notice,
                                weather=run_weather_agent(result.parsed))
