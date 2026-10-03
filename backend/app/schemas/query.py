from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.portfolio import Sector
from app.utils.text import clean_text

Intent = Literal[
    "event_impact", "portfolio_risk", "historical_search",
    "exposure", "explain_risk", "hedging", "other",
]
EventType = Literal[
    "hurricane", "tropical_storm", "earthquake", "flood",
    "wildfire", "geopolitical", "other", "none",
]
# Which pipeline stages the question needs. Phase 8's LangGraph router reads this.
AnalysisStep = Literal[
    "weather", "news", "market", "historical", "exposure", "scenario", "risk", "drivers", "fusion", "hedging",
]


class QueryIn(BaseModel):
    query: str = Field(min_length=3, max_length=500)

    @field_validator("query")
    @classmethod
    def sanitize(cls, v: str) -> str:
        cleaned = clean_text(v, 500)
        if len(cleaned) < 3:
            raise ValueError("query is too short")
        return cleaned


class ParsedQuery(BaseModel):
    """Structured meaning of the user's question (output of the Query Understanding agent)."""

    intent: Intent
    event_type: EventType = "none"
    event_category: int | None = Field(default=None, ge=1, le=5)
    region: str | None = Field(default=None, max_length=60)
    sectors: list[Sector] = []
    assets: list[str] = []           # tickers / asset names mentioned, e.g. ["XOM", "Crude oil"]
    uses_portfolio: bool = False     # True for "my holdings", "our portfolio", ...
    time_horizon: str | None = Field(default=None, max_length=40)
    time_horizon_days: int | None = Field(default=None, ge=1, le=365)
    # Calendar years the question is ABOUT when it asks about the past ("in 2010", "between 2005 and 2010").
    year_from: int | None = Field(default=None, ge=1850, le=2100)
    year_to: int | None = Field(default=None, ge=1850, le=2100)
    topics: list[str] = []           # extra aspects asked about (fixed vocabulary), e.g. "flooding", "damage"
    analysis_steps: list[AnalysisStep] = []
    # Self-reported by the LLM, or a simple field-count heuristic for the rule parser.
    # It is NOT a statistical probability.
    confidence: float = Field(ge=0, le=1)
    parser: Literal["llm", "rules"]
    llm_model: str | None = None     # which model produced this (LLM parser only)
    supported: bool = True           # False if the event type isn't covered by this MVP
    warnings: list[str] = []


class QueryParseResponse(BaseModel):
    query: str                       # the sanitised question that was analysed
    parsed: ParsedQuery
    # Human-readable note about HOW it was parsed (e.g. why the LLM wasn't used).
    notice: str | None = None
