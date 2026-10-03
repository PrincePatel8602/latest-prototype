"""Shared state that flows through the LangGraph pipeline.

Each node reads what it needs and returns ONLY the keys it changes (LangGraph merges them).
`runs` uses an "append" reducer so every node can add its own AgentRun entry.
"""
import operator
from typing import Annotated, TypedDict

from app.schemas.market import MarketIntelligence
from app.schemas.drivers import RiskDrivers
from app.schemas.fusion import FusionAssessment
from app.schemas.hedging import HedgingAnalysis
from app.schemas.historical import HistoricalIntelligence
from app.schemas.risk import ExposureAnalysis, ScenarioAnalysis, RiskAnalysis
from app.schemas.news import NewsIntelligence
from app.schemas.pipeline import AgentRun
from app.schemas.query import QueryParseResponse
from app.schemas.weather import WeatherIntelligence


class PipelineState(TypedDict, total=False):
    query: str                                   # sanitised question (input)
    parse: QueryParseResponse                    # output of Query Understanding
    pending: list[str]                           # analysis steps still to run, pipeline order
    runs: Annotated[list[AgentRun], operator.add]
    weather: WeatherIntelligence | None
    news: NewsIntelligence | None
    market: MarketIntelligence | None
    historical: HistoricalIntelligence | None
    exposure: ExposureAnalysis | None
    scenario: ScenarioAnalysis | None
    risk: RiskAnalysis | None
    drivers: RiskDrivers | None
    fusion: FusionAssessment | None
    hedging: HedgingAnalysis | None
