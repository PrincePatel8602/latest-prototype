"""Link physical impact (BSEE peak shut-in) to market response (event-study CAR). Pure Python, descriptive only.

For each series: the storms that have BOTH a BSEE shut-in maximum and a valid, non-overlapping event-study result are
compared two ways: a Spearman rank correlation and a high-vs-low split at HIGH_SHUTIN_PCT. Sample sizes are always
returned; with few storms the numbers are explicitly flagged as indicative only.
"""
from __future__ import annotations

import math
import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.models import EventStudyResult
from app.historical.physical.models import BseeStormShutin

HIGH_SHUTIN_PCT = 50.0
MIN_N_FOR_CORRELATION = 8


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1          # average rank for ties
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


def _stats(v: list[float]) -> dict:
    return {"n": len(v), "mean": statistics.fmean(v) if v else None, "median": statistics.median(v) if v else None}


def shutin_vs_response(session: Session, *, window: str = "0,5", exclude_overlap: bool = True,
                       series: tuple[str, ...] | None = None) -> dict[str, dict]:
    shut = {r.storm_id: r for r in session.scalars(select(BseeStormShutin).where(
        BseeStormShutin.storm_id.is_not(None), BseeStormShutin.max_oil_shut_in_pct.is_not(None)))}
    by_series: dict[str, list[tuple[str, float, float]]] = {}
    for r in session.scalars(select(EventStudyResult).where(EventStudyResult.status == "ok")):
        if r.storm_id not in shut or (series and r.series_key not in series):
            continue
        if exclude_overlap and r.overlap:
            continue
        by_series.setdefault(r.series_key, []).append((r.storm_id, shut[r.storm_id].max_oil_shut_in_pct, r.windows[window]["car"]))
    out: dict[str, dict] = {}
    for key, rows in sorted(by_series.items()):
        xs, ys = [r[1] for r in rows], [r[2] for r in rows]
        hi = [r[2] for r in rows if r[1] >= HIGH_SHUTIN_PCT]
        lo = [r[2] for r in rows if r[1] < HIGH_SHUTIN_PCT]
        out[key] = {"window": window, "n_storms": len(rows), "storm_ids": sorted(r[0] for r in rows),
                    "spearman_rho": spearman(xs, ys) if len(rows) >= MIN_N_FOR_CORRELATION else None,
                    f"high_shutin_ge_{int(HIGH_SHUTIN_PCT)}pct": _stats(hi), f"low_shutin_lt_{int(HIGH_SHUTIN_PCT)}pct": _stats(lo),
                    "caveat": ("Indicative only: few storms, Gulf-wide shut-in maxima, no causal claim."
                               if len(rows) < 30 else "Descriptive; no causal claim.")}
    return out
