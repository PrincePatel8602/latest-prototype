"""Hedging analysis output. Historical, measured and descriptive: not investment advice, no costs or option prices modelled."""
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import DataMeta


class HedgeCandidate(BaseModel):
    rank: int | None = None                   # by out-of-sample variance reduction (1 = best); None when not evaluable
    series_key: str
    name: str
    kind: str                                 # market | sector | commodity
    status: Literal["ok", "insufficient_history"]
    position: str = "short"
    hedge_ratio: float | None = None          # minimum-variance beta of the sleeve on this instrument
    notional_usd: float | None = None         # |hedge_ratio| x portfolio value
    notional_pct_of_portfolio: float | None = None
    correlation: float | None = None
    in_sample_variance_reduction_pct: float | None = None
    out_of_sample: dict[str, Any] | None = None
    before: dict[str, Any] | None = None      # volatility %, 95% 1-day VaR %, worst day % (of portfolio)
    after: dict[str, Any] | None = None
    storm_windows: dict[str, Any] | None = None
    note: str = ""


class TrimOption(BaseModel):
    symbol: str
    trim_fraction: float
    weight_before_pct: float
    weight_after_pct: float
    volatility_before_pct: float
    volatility_after_pct: float
    volatility_reduction_pct: float


class HedgingAnalysis(BaseModel):
    meta: DataMeta
    status: Literal["ok", "insufficient_data", "unavailable"]
    basis: dict[str, Any] = {}
    candidates: list[HedgeCandidate] = []
    trim_options: list[TrimOption] = []
    storm_context: dict[str, Any] | None = None
    not_modeled: list[str] = []
    conclusion: str
    limitations: list[str] = []
