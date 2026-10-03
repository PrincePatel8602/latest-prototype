"""Deterministic event-study mathematics (pure Python, no I/O, no LLM).

Method (standard market-model event study):
  * prices of an asset and the benchmark are inner-joined on common trading dates; returns are simple
    returns between consecutive COMMON dates, so asset and benchmark cover identical periods
  * t0 = first common trading date on/after the event anchor date
  * estimation window: trading days [t0-250, t0-31]; needs >= MIN_EST observations
  * market model r_asset = alpha + beta * r_benchmark estimated by OLS on that window
  * abnormal return AR_t = r_asset,t - (alpha + beta * r_benchmark,t)
  * CAR over a window = sum of AR; t-stat = CAR / (resid_std * sqrt(window length))
  * volatility ratio = stdev(raw returns in [0,+10]) / stdev(raw returns in the estimation window)
  * max drawdown = worst peak-to-trough decline of price over [t0-1, t0+10] (peak starts at the t0-1 close)

Nothing here says WHY a price moved. A CAR is a descriptive statistic, not a causal estimate.
"""
from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date

EST_START, EST_END = -250, -31
MIN_EST = 120
WINDOWS: tuple[tuple[int, int], ...] = ((-5, -1), (-1, 1), (0, 5), (0, 10))
MAX_ANCHOR_GAP_DAYS = 5
VOL_WINDOW = (0, 10)
DD_WINDOW = (-1, 10)
METHOD = {"model": "market_model_ols", "benchmark_return": "simple", "estimation_window": [EST_START, EST_END],
          "min_estimation_obs": MIN_EST, "windows": [list(w) for w in WINDOWS], "car": "sum_of_abnormal_returns"}


def wkey(w: tuple[int, int]) -> str:
    return f"{w[0]},{w[1]}"


@dataclass
class AssetEventResult:
    status: str                                # ok | no_data | before_data_start | after_data_end | anchor_gap | insufficient_estimation | insufficient_event_window | nonpositive_price
    t0: date | None = None
    n_est: int = 0
    alpha: float | None = None
    beta: float | None = None
    resid_std: float | None = None
    vol_ratio: float | None = None
    max_drawdown: float | None = None
    windows: dict[str, dict] = field(default_factory=dict)    # "0,5" -> {car, raw_return, t_stat, n_days}
    detail: str | None = None


def align(asset: dict[date, float], bench: dict[date, float]) -> tuple[list[date], list[float], list[float]]:
    """Common dates, asset prices, benchmark prices (sorted)."""
    dates = sorted(set(asset) & set(bench))
    return dates, [asset[d] for d in dates], [bench[d] for d in dates]


def simple_returns(prices: list[float]) -> list[float | None]:
    """r[i] = p[i]/p[i-1]-1 ; r[0] is None; None where the previous price is not positive."""
    out: list[float | None] = [None]
    for i in range(1, len(prices)):
        out.append(prices[i] / prices[i - 1] - 1 if prices[i - 1] > 0 else None)
    return out


def ols(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """alpha, beta, residual std (n-2 dof)."""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx == 0:
        raise ValueError("zero benchmark variance in estimation window")
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    alpha = my - beta * mx
    sse = sum((b - (alpha + beta * a)) ** 2 for a, b in zip(x, y))
    return alpha, beta, math.sqrt(sse / (n - 2))


def max_drawdown(prices: list[float]) -> float:
    peak, worst = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        worst = min(worst, p / peak - 1)
    return worst


def event_study(asset: dict[date, float], bench: dict[date, float], anchor: date) -> AssetEventResult:
    dates, pa, pb = align(asset, bench)
    if len(dates) < 2:
        return AssetEventResult("no_data", detail="fewer than 2 common trading dates")
    if anchor < dates[0]:
        return AssetEventResult("before_data_start", detail=f"series starts {dates[0]} (common with benchmark)")
    if anchor > dates[-1]:
        return AssetEventResult("after_data_end", detail=f"series ends {dates[-1]}")
    i0 = bisect_left(dates, anchor)
    if i0 >= len(dates) or (dates[i0] - anchor).days > MAX_ANCHOR_GAP_DAYS:
        return AssetEventResult("anchor_gap", detail="no common trading date within "
                                f"{MAX_ANCHOR_GAP_DAYS} days after the anchor")
    res = AssetEventResult("ok", t0=dates[i0])
    ra, rb = simple_returns(pa), simple_returns(pb)

    lo, hi = i0 + EST_START, i0 + EST_END
    est = [(rb[i], ra[i]) for i in range(max(lo, 1), hi + 1) if ra[i] is not None and rb[i] is not None]
    res.n_est = len(est)
    if len(est) < MIN_EST:
        res.status, res.detail = "insufficient_estimation", f"{len(est)} estimation observations (< {MIN_EST})"
        return res
    res.alpha, res.beta, res.resid_std = ols([e[0] for e in est], [e[1] for e in est])

    need_hi = i0 + max(w[1] for w in WINDOWS)
    need_lo = i0 + min(min(w[0] for w in WINDOWS), DD_WINDOW[0])
    if need_hi >= len(dates) or need_lo < 1:
        res.status, res.detail = "insufficient_event_window", "price history does not cover the full event window"
        return res
    if any(p <= 0 for p in pa[need_lo - 1:need_hi + 1]):
        res.status, res.detail = "nonpositive_price", "asset price <= 0 inside the event window; returns undefined"
        return res
    if any(ra[i] is None or rb[i] is None for i in range(need_lo, need_hi + 1)):
        res.status, res.detail = "insufficient_event_window", "missing return inside the event window"
        return res

    ar = {i: ra[i] - (res.alpha + res.beta * rb[i]) for i in range(need_lo, need_hi + 1)}
    for w in WINDOWS:
        idx = range(i0 + w[0], i0 + w[1] + 1)
        car = sum(ar[i] for i in idx)
        raw = math.prod(1 + ra[i] for i in idx) - 1
        n = len(idx)
        res.windows[wkey(w)] = {"car": car, "raw_return": raw, "n_days": n,
                                "t_stat": car / (res.resid_std * math.sqrt(n)) if res.resid_std else None}
    ev = [ra[i] for i in range(i0 + VOL_WINDOW[0], i0 + VOL_WINDOW[1] + 1)]
    base = [e[1] for e in est]
    if len(ev) >= 5 and statistics.pstdev(base) > 0:
        res.vol_ratio = statistics.stdev(ev) / statistics.stdev(base)
    res.max_drawdown = max_drawdown(pa[i0 + DD_WINDOW[0]:i0 + DD_WINDOW[1] + 1])
    return res


# ------------------------------------------------------------------ cross-event aggregation
def summarize(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0}
    mean = sum(values) / n
    out = {"n": n, "mean": mean, "median": statistics.median(values), "min": min(values), "max": max(values),
           "share_positive": sum(v > 0 for v in values) / n}
    if n >= 5:
        sd = statistics.stdev(values)
        out.update(std=sd, t_stat=(mean / (sd / math.sqrt(n))) if sd > 0 else None)
    else:
        out.update(std=None, t_stat=None, note="fewer than 5 events: no dispersion/t-stat reported")
    return out


def tradingday_overlap(anchors: dict[str, date], span_days: int = 21) -> dict[str, list[str]]:
    """storm_id -> other storm_ids whose anchor lies within +/- span_days calendar days (event windows would overlap)."""
    out: dict[str, list[str]] = {}
    items = sorted(anchors.items(), key=lambda kv: kv[1])
    for sid, d in items:
        out[sid] = [o for o, od in items if o != sid and abs((od - d).days) <= span_days]
    return out
