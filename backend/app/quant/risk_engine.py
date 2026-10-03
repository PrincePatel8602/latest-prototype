"""Phase 10 quantitative engine.

All arithmetic is performed here, not by the LLM. Scenario shocks are explicitly
model assumptions. Historical VaR is only returned when an actual return series is
provided; the engine never invents one.
"""
from math import sqrt
from statistics import pstdev
from app.schemas.portfolio import PortfolioResponse
from app.schemas.risk import ExposureAnalysis, ExposureItem, ScenarioAnalysis, ScenarioImpact, RiskAnalysis
from app.schemas.common import DataMeta
from app.services.common import now_utc

_ASSUMED_DAILY_VOL = {"XOM": 0.020, "CVX": 0.021, "UNG": 0.045}


def exposure(portfolio: PortfolioResponse) -> ExposureAnalysis:
    hhi = sum((h.weight_pct / 100) ** 2 for h in portfolio.holdings)
    items = [ExposureItem(symbol=h.symbol, name=h.name, sector=h.sector, weight_pct=h.weight_pct, value_usd=h.value_usd) for h in portfolio.holdings]
    largest = max((h.weight_pct for h in portfolio.holdings), default=0.0)
    return ExposureAnalysis(
        meta=DataMeta(source=portfolio.meta.source, notice="Calculated from the current portfolio held by the application.", as_of=now_utc()),
        total_value=portfolio.total_value,
        energy_exposure_pct=portfolio.energy_exposure_pct,
        largest_position_pct=round(largest, 2),
        concentration_hhi=round(hhi, 4),
        holdings=items,
        summary=f"Energy exposure is {portfolio.energy_exposure_pct:.1f}% and the largest position is {largest:.1f}% of portfolio value.",
    )


def scenario_hurricane(portfolio: PortfolioResponse) -> ScenarioAnalysis:
    # Explicit demo assumptions based on the project specification. These are not forecasts.
    shocks = {"XOM": 5.0, "CVX": 5.0, "UNG": 8.0}
    impacts: list[ScenarioImpact] = []
    total_pct = 0.0
    for h in portfolio.holdings:
        shock = shocks.get(h.symbol, 0.0)
        contribution = h.weight_pct / 100 * shock
        impacts.append(ScenarioImpact(
            symbol=h.symbol,
            shock_pct=shock,
            contribution_pct=round(contribution, 3),
            contribution_usd=round(portfolio.total_value * contribution / 100, 2),
            assumption="Illustrative hurricane scenario assumption; not a market forecast." if shock else "No shock specified for this holding in the illustrative scenario.",
        ))
        total_pct += contribution
    total_usd = portfolio.total_value * total_pct / 100
    return ScenarioAnalysis(
        meta=DataMeta(source="demo", notice="Scenario shocks are explicit model assumptions from the project demo specification.", as_of=now_utc()),
        name="Category 4 Gulf hurricane — illustrative stress scenario",
        assumptions=[
            "XOM +5%",
            "CVX +5%",
            "UNG +8%",
            "Other holdings 0% unless explicitly modeled",
            "These shocks are assumptions for stress testing, not predicted returns.",
        ],
        impacts=impacts,
        estimated_portfolio_change_pct=round(total_pct, 3),
        estimated_portfolio_change_usd=round(total_usd, 2),
        summary=f"Under the illustrative assumptions, the weighted portfolio change is {total_pct:.2f}% ({total_usd:,.0f} USD).",
    )


def _assumption_volatility(portfolio: PortfolioResponse) -> float:
    # Weighted one-day volatility proxy. Clearly labeled as an assumption-based estimate.
    variance = 0.0
    for h in portfolio.holdings:
        sigma = _ASSUMED_DAILY_VOL.get(h.symbol, 0.015)
        variance += (h.weight_pct / 100) ** 2 * sigma ** 2
    return sqrt(variance) * sqrt(252) * 100


def risk(portfolio: PortfolioResponse, scenario: ScenarioAnalysis | None, returns: dict[str, list[float]] | None = None) -> RiskAnalysis:
    hhi = sum((h.weight_pct / 100) ** 2 for h in portfolio.holdings)
    concentration_score = min(100.0, hhi * 10000)
    vol = None
    vol_method = "not_available"
    var = None
    var_method = "not_available"
    limitations: list[str] = []

    if returns and all(returns.get(h.symbol) for h in portfolio.holdings if h.symbol != "OTHER"):
        # Simple weighted portfolio return series when real returns are supplied.
        n = min(len(v) for v in returns.values())
        series = []
        for i in range(n):
            r = 0.0
            for h in portfolio.holdings:
                if h.symbol == "OTHER":
                    continue
                r += h.weight_pct / 100 * returns[h.symbol][i]
            series.append(r)
        if len(series) >= 2:
            vol = pstdev(series) * sqrt(252) * 100
            ordered = sorted(series)
            var = -ordered[max(0, int(len(ordered) * 0.05) - 1)] * 100
            vol_method = "historical_return_series"
            var_method = "historical_95_percentile"
            other = sum(h.weight_pct for h in portfolio.holdings if h.symbol == "OTHER")
            limitations.append(f"Volatility and VaR use stored daily returns of the {len(series)}-day common history of the holdings with price data; "
                               f"'Other assets' ({other:.0f}% of the portfolio) are excluded.")
    else:
        vol = _assumption_volatility(portfolio)
        vol_method = "assumption_based_weighted_volatility"
        limitations.append("No historical asset-return series is connected yet; volatility is an explicitly labeled assumption-based proxy.")
        limitations.append("Historical VaR is withheld until actual return observations are available.")

    scenario_change = scenario.estimated_portfolio_change_pct if scenario else None
    score = min(100.0, 0.45 * concentration_score + 0.35 * min(vol or 0, 100) + 0.20 * min(abs(scenario_change or 0) * 10, 100))
    level = "LOW" if score < 35 else "MODERATE" if score < 60 else "HIGH" if score < 80 else "EXTREME"
    return RiskAnalysis(
        meta=(DataMeta(source="live", notice="Volatility and VaR are calculated by Python from stored daily returns; the scenario shocks remain explicit assumptions.", as_of=now_utc())
              if vol_method == "historical_return_series" else
              DataMeta(source="demo", notice="Risk metrics are calculated by Python; assumptions and data limitations are shown explicitly.", as_of=now_utc())),
        risk_level=level,
        risk_score=round(score, 1),
        volatility_pct=round(vol, 2) if vol is not None else None,
        volatility_method=vol_method,
        concentration_score=round(concentration_score, 1),
        scenario_change_pct=scenario_change,
        scenario_change_usd=scenario.estimated_portfolio_change_usd if scenario else None,
        historical_var_95_pct=round(var, 2) if var is not None else None,
        historical_var_method=var_method,
        limitations=limitations,
        summary=f"Quantitative risk score is {score:.1f}/100 ({level}); concentration and the selected scenario are included in the calculation.",
    )
