"""Evidence-fusion output. All return figures are PERCENT of the stated base and DESCRIBE history; none is a forecast."""
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import DataMeta

Grade = Literal["insufficient_data", "not_distinguishable_from_zero", "weak_signal", "indicative"]


class DistributionStats(BaseModel):
    n: int
    median: float | None = None
    mean: float | None = None
    p10: float | None = None
    p90: float | None = None
    min: float | None = None
    max: float | None = None
    share_positive: float | None = None
    mean_ci_low: float | None = None          # 90% bootstrap interval of the mean
    mean_ci_high: float | None = None
    grade: Grade = "insufficient_data"


class AssetEvidence(BaseModel):
    symbol: str
    series_key: str | None
    weight_pct: float
    covered: bool                              # False: no stored price history / event study for this holding
    stats: DistributionStats | None = None     # 5-day abnormal return (%) over analog storms
    scenario_shock_pct: float | None = None   # the Phase 10 ASSUMPTION for this holding, if any
    scenario_vs_history: str | None = None    # within_historical_range | above_ | below_ | no_history


class StormPoint(BaseModel):
    """One past storm's result: the dot behind the distribution."""
    storm_id: str
    label: str                                 # "Katrina 2005"
    year: int
    value_pct: float                           # sleeve 5-day abnormal return, % of portfolio
    independent: bool                          # False when another Gulf storm was close in time


class PortfolioEvidence(BaseModel):
    symbols: list[str]
    covered_weight_pct: float                  # share of the portfolio the estimate speaks about
    uncovered_weight_pct: float
    basis: str                                 # what the % are a percentage of
    all_analogs: DistributionStats             # sleeve contribution (% of TOTAL portfolio), 5-day abnormal return
    independent_only: DistributionStats        # sensitivity: storms without another Gulf storm nearby
    per_storm: list[StormPoint] = []
    median_usd: float | None = None
    p10_usd: float | None = None
    p90_usd: float | None = None
    scenario_change_pct: float | None = None   # Phase 10 assumption for the same sleeve (% of total portfolio)
    scenario_vs_history: str | None = None


class ContextLayer(BaseModel):
    """A live or physical evidence layer shown NEXT TO the estimate, never blended into it."""
    layer: str
    status: str
    summary: str
    used_in_estimate: bool = False
    reason: str


class FusionAssessment(BaseModel):
    meta: DataMeta
    status: Literal["ok", "insufficient_evidence", "unavailable", "unsupported_event"]
    event: dict[str, Any]
    analogs: dict[str, Any]                    # selection rule, counts, storm list
    window: str = "0,5"
    assets: list[AssetEvidence] = []
    portfolio: PortfolioEvidence | None = None
    physical_context: dict[str, Any] | None = None
    historical_risk: dict[str, Any] | None = None
    context_layers: list[ContextLayer] = []
    method: dict[str, Any] = {}
    conclusion: str
    limitations: list[str] = []
