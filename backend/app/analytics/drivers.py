"""Portfolio risk-driver statistics from REAL stored prices (pure Python, no I/O, no LLM).

Answers "did my risk change, and what drives it?" for the holdings that have price history:
  * recent realised volatility of the weighted sleeve vs its own trailing year and its own 3-year history
  * each holding's share of sleeve variance (weight * cov(r_i, r_sleeve) / var(r_sleeve)), recent vs trailing year
  * recent holding returns
Thresholds are plain conventions (quintiles of the sleeve's own history), not tuned weights.
"""
from __future__ import annotations

import math
import statistics
from datetime import date

RECENT = 20            # trading days ("last month")
YEAR = 252
HISTORY = 756          # ~3 years of daily data for the percentile
HIGH_PCT, LOW_PCT = 80.0, 20.0
MIN_DAYS = 120


def aligned_returns(prices: dict[str, dict[date, float]]) -> tuple[list[date], dict[str, list[float]]]:
    """Simple daily returns on dates where EVERY symbol has a price and a previous price on its own calendar."""
    from app.analytics.fusion import returns_from_prices
    rets = {s: returns_from_prices(p) for s, p in prices.items()}
    if not rets:
        return [], {}
    common = sorted(set.intersection(*[set(r) for r in rets.values()]))
    return common, {s: [rets[s][d] for d in common] for s in rets}


def sleeve_series(rets: dict[str, list[float]], weights: dict[str, float]) -> list[float]:
    n = len(next(iter(rets.values())))
    return [sum(weights[s] * rets[s][i] for s in weights) for i in range(n)]


def ann_vol_pct(xs: list[float]) -> float:
    return statistics.stdev(xs) * math.sqrt(252) * 100


def percentile_rank(history: list[float], value: float) -> float:
    """Share of `history` values <= value, in percent."""
    return 100.0 * sum(h <= value for h in history) / len(history)


def variance_shares(rets: dict[str, list[float]], weights: dict[str, float], window: int) -> dict[str, float]:
    """symbol -> share (percent) of the sleeve's variance over the last `window` days; shares sum to 100."""
    r = {s: v[-window:] for s, v in rets.items()}
    port = sleeve_series(r, weights)
    var_p = statistics.variance(port)
    if var_p == 0:
        return {s: 0.0 for s in weights}
    return {s: 100.0 * weights[s] * statistics.covariance(r[s], port) / var_p for s in weights}


def compound(xs: list[float]) -> float:
    return math.prod(1 + x for x in xs) - 1


def classify(percentile: float) -> str:
    return "elevated" if percentile >= HIGH_PCT else "subdued" if percentile <= LOW_PCT else "typical"


def analyse(prices: dict[str, dict[date, float]], weights: dict[str, float]) -> dict | None:
    """None when there is not enough common history (< MIN_DAYS) to say anything."""
    dates, rets = aligned_returns({s: p for s, p in prices.items() if s in weights})
    if len(rets) != len(weights) or len(dates) < MIN_DAYS:
        return None
    port = sleeve_series(rets, weights)
    recent, year = port[-RECENT:], port[-YEAR:]
    hist_n = min(len(port), HISTORY)
    rolling = [ann_vol_pct(port[i - RECENT:i]) for i in range(len(port) - hist_n + RECENT, len(port) + 1)]
    recent_vol, year_vol = ann_vol_pct(recent), ann_vol_pct(year)
    pct = percentile_rank(rolling, recent_vol)
    shares_recent, shares_year = variance_shares(rets, weights, RECENT), variance_shares(rets, weights, min(YEAR, len(port)))
    holdings = []
    for s in sorted(weights):
        holdings.append({
            "symbol": s, "weight_pct": weights[s] * 100,
            "risk_share_recent_pct": shares_recent[s], "risk_share_year_pct": shares_year[s],
            "return_recent_pct": compound(rets[s][-RECENT:]) * 100,
            "volatility_recent_pct": ann_vol_pct(rets[s][-RECENT:]), "volatility_year_pct": ann_vol_pct(rets[s][-YEAR:])})
    window_ends = range(len(port) - hist_n + RECENT, len(port) + 1)          # same windows as `rolling`
    series = [{"date": dates[i - 1].isoformat(), "vol_pct": v} for i, v in zip(window_ends, rolling)][-YEAR:]
    return {
        "rolling_volatility": series, "as_of": dates[-1], "days_used": len(dates), "recent_window_days": RECENT,
        "recent_vol_pct": recent_vol, "year_vol_pct": year_vol, "vol_ratio": recent_vol / year_vol if year_vol else None,
        "history_percentile": pct, "history_days": hist_n, "classification": classify(pct),
        "sleeve_return_recent_pct": compound(recent) * 100, "holdings": holdings,
        "top_risk_symbol": max(holdings, key=lambda h: h["risk_share_recent_pct"])["symbol"]}
