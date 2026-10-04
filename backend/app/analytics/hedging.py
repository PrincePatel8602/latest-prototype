"""Hedge evaluation from real stored returns (pure Python, no I/O, no LLM, no assumed costs or views).

For a candidate hedge instrument h and the portfolio sleeve return r_s (sum of weight_i * r_i, weights as fractions of the
WHOLE portfolio):
  * minimum-variance hedge ratio  beta = cov(r_s, r_h) / var(r_h)   (short beta * portfolio value of h)
  * hedged return                 r_s - beta * r_h
  * in-sample variance reduction  = R^2 of the regression (share of variance the hedge removes)
  * out-of-sample reduction       = beta estimated on the OLDER part of the history, applied to the most RECENT part
  * tail effect                   = 95% 1-day historical VaR and worst day, before vs after
The ranking rule is the out-of-sample variance reduction. Costs, margin, borrow, taxes and option prices are NOT modelled.
"""
from __future__ import annotations

import math
import statistics

from app.analytics.fusion import percentile, summarize

TRAIN_DAYS, TEST_DAYS = 504, 252
MIN_DAYS = 300


def beta_r2(rs: list[float], rh: list[float]) -> tuple[float, float]:
    """OLS slope of rs on rh and the regression R^2."""
    var_h = statistics.variance(rh)
    if var_h == 0:
        raise ValueError("hedge instrument has zero variance")
    cov = statistics.covariance(rh, rs)
    beta = cov / var_h
    var_s = statistics.variance(rs)
    r2 = (cov * cov) / (var_h * var_s) if var_s else 0.0
    return beta, r2


def hedged(rs: list[float], rh: list[float], beta: float) -> list[float]:
    return [a - beta * b for a, b in zip(rs, rh)]


def _tail(xs: list[float]) -> dict:
    s = sorted(xs)
    return {"volatility_pct": statistics.stdev(xs) * math.sqrt(252) * 100, "var95_1d_pct": -percentile(s, 0.05) * 100,
            "worst_day_pct": s[0] * 100}


def variance_reduction(before: list[float], after: list[float]) -> float:
    vb = statistics.variance(before)
    return 100.0 * (1 - statistics.variance(after) / vb) if vb else 0.0


def evaluate(rs: list[float], rh: list[float]) -> dict | None:
    """Full evaluation of one hedge on aligned daily returns; None if there is not enough history."""
    n = len(rs)
    if n < MIN_DAYS or len(rh) != n:
        return None
    beta, r2 = beta_r2(rs, rh)
    out = {"days": n, "hedge_ratio": beta, "in_sample_variance_reduction_pct": 100 * r2,
           "correlation": math.copysign(math.sqrt(r2), beta), "before": _tail(rs), "after": _tail(hedged(rs, rh, beta))}
    test = min(TEST_DAYS, n // 3)
    train_s, train_h, test_s, test_h = rs[:-test], rh[:-test], rs[-test:], rh[-test:]
    b_train, _ = beta_r2(train_s, train_h)
    out["out_of_sample"] = {"train_days": len(train_s), "test_days": test, "hedge_ratio_train": b_train,
                            "variance_reduction_pct": variance_reduction(test_s, hedged(test_s, test_h, b_train))}
    return out


def trim_effect(rets: dict[str, list[float]], weights: dict[str, float], symbol: str, fraction: float) -> dict:
    """What if `fraction` of `symbol`'s position moved to cash (zero return)? Volatility of the sleeve before/after."""
    base = [sum(weights[s] * rets[s][i] for s in weights) for i in range(len(next(iter(rets.values()))))]
    w2 = dict(weights)
    w2[symbol] = weights[symbol] * (1 - fraction)
    new = [sum(w2[s] * rets[s][i] for s in w2) for i in range(len(base))]
    vb, va = statistics.stdev(base) * math.sqrt(252) * 100, statistics.stdev(new) * math.sqrt(252) * 100
    return {"symbol": symbol, "trim_fraction": fraction, "weight_before_pct": weights[symbol] * 100, "weight_after_pct": w2[symbol] * 100,
            "volatility_before_pct": vb, "volatility_after_pct": va, "volatility_reduction_pct": 100 * (1 - va / vb) if vb else 0.0}


def storm_windows(sleeve: dict[str, float], hedge: dict[str, float], beta: float) -> dict | None:
    """Per-storm window returns (fractions) -> unhedged vs hedged distributions (percent) on the JOINT sample of storms."""
    ids = sorted(set(sleeve) & set(hedge))
    if not ids:
        return None
    un = [sleeve[i] * 100 for i in ids]
    hd = [(sleeve[i] - beta * hedge[i]) * 100 for i in ids]
    su, sh = summarize(un), summarize(hd)
    return {"n": len(ids), "unhedged": su, "hedged": sh,
            "dispersion_unhedged_pct": statistics.stdev(un) if len(un) > 1 else None,
            "dispersion_hedged_pct": statistics.stdev(hd) if len(hd) > 1 else None,
            "hedged_better_in_worst_case": min(hd) > min(un) if ids else None}
