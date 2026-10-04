"""Pure statistics for the evidence-fusion engine (no I/O, no LLM, no hand-picked weights).

Principles
  * The numeric estimate comes ONLY from calibrated evidence: stored event-study abnormal returns (CARs) of analogous
    historical storms, combined with the portfolio's own weights (arithmetic on real data).
  * Evidence is graded by simple, published statistical rules (sample size, bootstrap interval vs zero), not by weights.
  * Bootstrap resamples whole STORMS, so cross-asset correlation inside a storm is preserved.
  * Everything is deterministic (seeded) so identical inputs give identical outputs.
"""
from __future__ import annotations

import math
import random
import statistics
from datetime import date

SEED = 20260101
BOOT_N = 2000
MIN_N = 5                      # fewer storms than this: no inference is offered
CI_LEVEL = 0.90                # two-sided bootstrap interval for the MEAN abnormal return


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]) of an already sorted list."""
    if not sorted_vals:
        raise ValueError("empty")
    pos = q * (len(sorted_vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap_mean_ci(values: list[float], *, level: float = CI_LEVEL, n_boot: int = BOOT_N, seed: int = SEED) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    a = (1 - level) / 2
    return percentile(means, a), percentile(means, 1 - a)


def grade(n: int, ci: tuple[float, float] | None) -> str:
    """insufficient_data | not_distinguishable_from_zero | indicative (interval excludes zero, n>=10) | weak_signal."""
    if n < MIN_N or ci is None:
        return "insufficient_data"
    if ci[0] <= 0 <= ci[1]:
        return "not_distinguishable_from_zero"
    return "indicative" if n >= 10 else "weak_signal"


def summarize(values: list[float], *, seed: int = SEED) -> dict:
    """Distribution summary in the SAME unit as `values` (callers pass percent)."""
    n = len(values)
    if n == 0:
        return {"n": 0, "grade": "insufficient_data"}
    s = sorted(values)
    out = {"n": n, "median": statistics.median(s), "mean": sum(s) / n, "p10": percentile(s, 0.10), "p90": percentile(s, 0.90),
           "min": s[0], "max": s[-1], "share_positive": sum(v > 0 for v in s) / n}
    ci = bootstrap_mean_ci(s, seed=seed) if n >= MIN_N else None
    out["mean_ci_low"], out["mean_ci_high"] = (ci if ci else (None, None))
    out["grade"] = grade(n, ci)
    return out


def portfolio_series(per_storm: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    """storm_id -> sum_i w_i * car_i, using ONLY storms where every weighted symbol has a result (joint sample)."""
    out = {}
    for sid, cars in per_storm.items():
        if all(sym in cars for sym in weights):
            out[sid] = sum(w * cars[sym] for sym, w in weights.items())
    return out


def vs_range(value: float, p10: float | None, p90: float | None) -> str:
    """Where an assumed value sits against the empirical 10th-90th percentile range."""
    if p10 is None or p90 is None:
        return "no_history"
    if value < p10:
        return "below_historical_range"
    if value > p90:
        return "above_historical_range"
    return "within_historical_range"


# ------------------------------------------------------------------ price-based risk (real data)
def returns_from_prices(prices: dict[date, float]) -> dict[date, float]:
    d = sorted(prices)
    return {d[i]: prices[d[i]] / prices[d[i - 1]] - 1 for i in range(1, len(d)) if prices[d[i - 1]] > 0}


def sleeve_risk(prices: dict[str, dict[date, float]], weights: dict[str, float], *, max_days: int = 756) -> dict | None:
    """Historical volatility and 95% 1-day VaR of the weighted sleeve over the most recent common trading days.

    `weights` are fractions of the WHOLE portfolio, so the figures are the sleeve's contribution to portfolio risk.
    Returns None when there are fewer than 60 common days (not enough to say anything).
    """
    rets = {s: returns_from_prices(p) for s, p in prices.items() if s in weights}
    if len(rets) != len(weights):
        return None
    common = sorted(set.intersection(*[set(r) for r in rets.values()]))[-max_days:]
    if len(common) < 60:
        return None
    series = [sum(weights[s] * rets[s][d] for s in weights) for d in common]
    ordered = sorted(series)
    return {"days": len(common), "start": common[0].isoformat(), "end": common[-1].isoformat(),
            "annualised_volatility_pct": statistics.stdev(series) * math.sqrt(252) * 100,
            "var95_1d_pct": -percentile(ordered, 0.05) * 100,
            "worst_day_pct": ordered[0] * 100,
            "daily_std_pct": statistics.stdev(series) * 100}
