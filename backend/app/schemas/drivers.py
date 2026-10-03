"""Risk-driver output: what the stored price history says about recent portfolio risk. Descriptive, not a forecast."""
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import DataMeta
from app.schemas.fusion import ContextLayer


class HoldingDriver(BaseModel):
    symbol: str
    weight_pct: float
    risk_share_recent_pct: float          # share of the sleeve's variance over the last ~20 trading days
    risk_share_year_pct: float            # same over the last ~year
    return_recent_pct: float
    volatility_recent_pct: float
    volatility_year_pct: float


class RiskChange(BaseModel):
    window_days: int
    recent_vol_pct: float                 # annualised volatility of the weighted sleeve, last ~20 trading days
    year_vol_pct: float
    vol_ratio: float | None = None
    history_percentile: float             # where recent volatility ranks among all rolling windows of the past ~3 years
    history_days: int
    classification: Literal["elevated", "typical", "subdued"]
    sleeve_return_recent_pct: float


class RollingPoint(BaseModel):
    date: str
    vol_pct: float


class RiskDrivers(BaseModel):
    meta: DataMeta
    status: Literal["ok", "insufficient_data", "unavailable"]
    prices_as_of: str | None = None
    prices_stale: bool = False
    covered_weight_pct: float = 0.0
    uncovered_weight_pct: float = 0.0
    risk_change: RiskChange | None = None
    holdings: list[HoldingDriver] = []
    rolling_volatility: list[RollingPoint] = []      # annualised 20-day volatility of the modeled holdings, last ~year
    concentration: dict[str, Any] = {}
    context_layers: list[ContextLayer] = []
    conclusion: str
    limitations: list[str] = []
