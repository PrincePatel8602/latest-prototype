from pydantic import BaseModel, Field
from app.schemas.common import DataMeta


class ExposureItem(BaseModel):
    symbol: str
    name: str
    sector: str
    weight_pct: float
    value_usd: float


class ExposureAnalysis(BaseModel):
    meta: DataMeta
    total_value: float
    energy_exposure_pct: float
    largest_position_pct: float
    concentration_hhi: float
    holdings: list[ExposureItem] = []
    summary: str


class ScenarioImpact(BaseModel):
    symbol: str
    shock_pct: float
    contribution_pct: float
    contribution_usd: float
    assumption: str


class ScenarioAnalysis(BaseModel):
    meta: DataMeta
    name: str
    assumptions: list[str] = []
    impacts: list[ScenarioImpact] = []
    estimated_portfolio_change_pct: float
    estimated_portfolio_change_usd: float
    summary: str


class RiskAnalysis(BaseModel):
    meta: DataMeta
    risk_level: str
    risk_score: float = Field(ge=0, le=100)
    volatility_pct: float | None = None
    volatility_method: str
    concentration_score: float
    scenario_change_pct: float | None = None
    scenario_change_usd: float | None = None
    historical_var_95_pct: float | None = None
    historical_var_method: str
    limitations: list[str] = []
    summary: str
