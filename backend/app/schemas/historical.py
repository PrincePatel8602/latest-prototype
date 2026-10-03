"""Historical-data API/agent schemas (Phase 11).

Everything here is a description of what NOAA recorded. Nothing in these models is a market
impact, a return, or a prediction.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DataMeta


class HistoricalStorm(BaseModel):
    """One stored historical storm (mirrors app.historical.repository.storm_to_dict)."""
    model_config = ConfigDict(extra="allow")

    postgres_id: int
    event_id: str
    storm_id: str
    name: str
    year: int
    basin: str
    region: str
    event_type: str
    start_datetime: str
    end_datetime: str
    duration_hours: float | None = None
    max_wind_kt: float | None = None
    max_wind_mph: float | None = None
    min_pressure_mb: float | None = None
    max_category_normalized: int | None = None
    max_category_original: int | None = None
    category_source: str | None = None
    track_length_km: float | None = None
    n_observations: int
    gulf_of_mexico_entered: bool
    max_category_in_gulf: int | None = None
    landfall_indicator_observations: int = 0
    data_quality_status: str
    quality_flags: dict[str, Any] = {}
    provenance: dict[str, Any]       # source, dataset_version, source_url, postgres{}, pinecone{}


class HistoricalSearchRequest(BaseModel):
    name: str | None = None
    basin: str | None = None
    event_type: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    min_category: int | None = Field(default=None, ge=-1, le=5)
    max_category: int | None = Field(default=None, ge=-1, le=5)
    category_scope: Literal["overall", "gulf"] = "overall"
    gulf_of_mexico: bool = False
    min_wind_kt: float | None = Field(default=None, ge=0)
    query: str | None = Field(default=None, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    use_semantic: bool = True
    category_target: int | None = Field(default=None, ge=-1, le=5)


class HistoricalSearchHit(BaseModel):
    storm: HistoricalStorm
    retrieval_method: str                      # structured+semantic | structured | semantic | structured_unfiltered
    similarity_score: float | None = None      # raw Pinecone score; None when Pinecone did not return it
    match_reasons: list[str] = []


class HistoricalSearchResponse(BaseModel):
    hits: list[HistoricalSearchHit]
    retrieval_method: str
    semantic_status: str
    notices: list[str] = []
    structured_candidates: int = 0
    semantic_candidates: int = 0
    applied_filters: dict[str, Any] = {}


class MarketResponse(BaseModel):
    """Descriptive event-study statistic for one storm x one price series (never a prediction or a cause)."""
    model_config = ConfigDict(extra="allow")

    series_key: str
    name: str
    status: str                                # ok | before_data_start | insufficient_estimation | ...
    detail: str | None = None
    anchor: str
    anchor_date: str
    t0_date: str | None = None
    window: str = "0,5"
    car: float | None = None                   # cumulative abnormal return vs SPY market model (fraction, 0.01 = 1%)
    raw_return: float | None = None
    t_stat: float | None = None
    beta: float | None = None
    n_estimation: int = 0
    vol_ratio: float | None = None
    max_drawdown: float | None = None
    overlap: bool = False
    provenance: dict[str, Any] = {}


class PhysicalImpact(BaseModel):
    """BSEE-reported Gulf of Mexico offshore production shut-ins during the storm (Gulf-wide, from daily press releases)."""
    max_oil_shut_in_pct: float | None = None
    max_gas_shut_in_pct: float | None = None
    max_platforms_evacuated: float | None = None
    peak_oil_date: str | None = None
    n_reports_used: int = 0
    n_reports_listed: int = 0
    source: str = "BSEE storm activity statistics"
    source_urls: list[str] = []
    note: str = ""


class HistoricalMatch(BaseModel):
    storm: HistoricalStorm
    physical_impact: PhysicalImpact | None = None
    market_response: list[MarketResponse] = []
    retrieval_method: str
    similarity_score: float | None = None
    match_reasons: list[str] = []


class HistoricalIntelligence(BaseModel):
    """Historical Agent output (LangGraph `historical` step)."""
    meta: DataMeta
    status: Literal["ok", "no_results", "unsupported_event", "unavailable"]
    query: dict
    matches: list[HistoricalMatch] = []
    retrieval_method: str = "none"
    semantic_status: str = "not_run"
    market_response_note: str | None = None
    dataset: dict[str, Any] = {}               # source / version / last ingestion (freshness)
    notices: list[str] = []
    summary: str
