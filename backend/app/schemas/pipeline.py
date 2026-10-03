"""Contracts for the full query pipeline (POST /api/query) and the per-agent endpoints."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.market import MarketIntelligence
from app.schemas.drivers import RiskDrivers
from app.schemas.fusion import FusionAssessment
from app.schemas.hedging import HedgingAnalysis
from app.schemas.historical import HistoricalIntelligence
from app.schemas.risk import ExposureAnalysis, ScenarioAnalysis, RiskAnalysis
from app.schemas.news import NewsIntelligence
from app.schemas.query import AnalysisStep, ParsedQuery
from app.schemas.weather import WeatherIntelligence
from app.utils.text import clean_text

RunStatus = Literal["completed", "failed", "not_implemented"]


class AgentRun(BaseModel):
    """What happened to ONE analysis step requested by the ParsedQuery."""

    step: AnalysisStep
    status: RunStatus
    note: str | None = None


class QueryPipelineResponse(BaseModel):
    query: str
    parsed: ParsedQuery
    parse_notice: str | None = None
    # None = the step was not requested, is not implemented yet, or failed (see `steps`).
    weather: WeatherIntelligence | None = None
    news: NewsIntelligence | None = None
    market: MarketIntelligence | None = None
    historical: HistoricalIntelligence | None = None
    exposure: ExposureAnalysis | None = None
    scenario: ScenarioAnalysis | None = None
    risk: RiskAnalysis | None = None
    drivers: RiskDrivers | None = None
    fusion: FusionAssessment | None = None
    hedging: HedgingAnalysis | None = None
    steps: list[AgentRun] = []        # one entry per ParsedQuery.analysis_steps, in pipeline order
    orchestrator: str = "langgraph"


class AnalyzeIn(BaseModel):
    """Body of POST /api/news/analyze and /api/market/analyze: a question OR a parsed query."""

    query: str | None = Field(default=None, min_length=3, max_length=500)
    parsed: ParsedQuery | None = None

    @field_validator("query")
    @classmethod
    def sanitize(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = clean_text(v, 500)
        if len(cleaned) < 3:
            raise ValueError("query is too short")
        return cleaned

    @model_validator(mode="after")
    def exactly_one(self) -> "AnalyzeIn":
        if (self.query is None) == (self.parsed is None):
            raise ValueError("provide exactly one of 'query' or 'parsed'")
        return self


class NewsAgentResponse(BaseModel):
    query: str | None
    parsed: ParsedQuery
    parse_notice: str | None = None
    news: NewsIntelligence


class MarketAgentResponse(BaseModel):
    query: str | None
    parsed: ParsedQuery
    parse_notice: str | None = None
    market: MarketIntelligence
