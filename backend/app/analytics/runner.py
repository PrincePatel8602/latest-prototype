"""Compute and persist event-study results for every stored Gulf storm and every price series."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import event_study as es
from app.analytics.models import EventStudyResult
from app.historical.geo import GULF_POLYGON_NOTE, in_gulf
from app.historical.market.models import MarketObservation, MarketSeries
from app.historical.models import HistoricalStorm, StormTrackPoint

log = logging.getLogger("aegis.analytics.event_study")
BENCHMARK = "yahoo:SPY"
ANCHOR = "gulf_entry"
ASSET_CATEGORIES = ("equity", "etf", "commodity")


@dataclass
class RunSummary:
    storms: int = 0
    assets: int = 0
    rows: int = 0
    by_status: dict = field(default_factory=dict)
    skipped_storms: list = field(default_factory=list)

    def render(self) -> str:
        return (f"Event study: {self.storms} Gulf storms x {self.assets} assets = {self.rows} results\n"
                f"Status counts: {self.by_status}\n"
                + (f"Storms without an anchor: {self.skipped_storms}\n" if self.skipped_storms else ""))


def load_prices(session: Session, series_key: str) -> dict[date, float]:
    """Total-return price where available (adj_close), otherwise the quoted value."""
    rows = session.execute(select(MarketObservation.obs_date, MarketObservation.value, MarketObservation.adj_close)
                           .where(MarketObservation.series_key == series_key))
    return {d: (adj if adj is not None else v) for d, v, adj in rows}


def gulf_anchors(session: Session) -> tuple[dict[str, date], dict[str, HistoricalStorm]]:
    storms = {s.storm_id: s for s in session.scalars(
        select(HistoricalStorm).where(HistoricalStorm.gulf_of_mexico_entered.is_(True)))}
    first: dict[str, datetime] = {}
    q = select(StormTrackPoint.storm_id, StormTrackPoint.timestamp, StormTrackPoint.latitude, StormTrackPoint.longitude
               ).where(StormTrackPoint.storm_id.in_(list(storms))).order_by(StormTrackPoint.storm_id, StormTrackPoint.timestamp)
    for sid, ts, lat, lon in session.execute(q):
        if sid not in first and in_gulf(lat, lon):
            first[sid] = ts
    return {sid: ts.date() for sid, ts in first.items()}, storms


def run_event_study(session: Session) -> RunSummary:
    now = datetime.now(timezone.utc)
    anchors, storms = gulf_anchors(session)
    out = RunSummary(storms=len(anchors), skipped_storms=sorted(set(storms) - set(anchors)))
    bench_meta = session.scalar(select(MarketSeries).where(MarketSeries.series_key == BENCHMARK))
    if bench_meta is None:
        raise RuntimeError(f"benchmark series {BENCHMARK} is not loaded; run scripts/import_market.py")
    bench = load_prices(session, BENCHMARK)
    overlap = es.tradingday_overlap(anchors)
    assets = list(session.scalars(select(MarketSeries).where(MarketSeries.category.in_(ASSET_CATEGORIES))
                                  .where(MarketSeries.series_key != BENCHMARK).order_by(MarketSeries.series_key)))
    out.assets = len(assets)
    storm_ver = next(iter(storms.values())).source_version if storms else None

    session.execute(delete(EventStudyResult).where(EventStudyResult.storm_id.in_(list(anchors))))   # regenerate wholesale
    for meta in assets:
        prices = load_prices(session, meta.series_key)
        for sid, anchor in sorted(anchors.items(), key=lambda kv: kv[1]):
            r = es.event_study(prices, bench, anchor)
            others = overlap.get(sid, [])
            session.add(EventStudyResult(
                storm_id=sid, series_key=meta.series_key, anchor=ANCHOR, anchor_date=anchor, t0_date=r.t0,
                status=r.status, detail=r.detail, n_estimation=r.n_est, alpha=r.alpha, beta=r.beta,
                resid_std=r.resid_std, vol_ratio=r.vol_ratio, max_drawdown=r.max_drawdown, overlap=bool(others),
                overlapping_storms=others, windows=r.windows or None, method=es.METHOD,
                provenance={"anchor_definition": f"first track point inside {GULF_POLYGON_NOTE}",
                            "benchmark": BENCHMARK, "benchmark_raw_sha256": bench_meta.raw_file_sha256,
                            "asset_raw_sha256": meta.raw_file_sha256, "asset_source": meta.source,
                            "storm_source": "NOAA IBTrACS", "storm_source_version": storm_ver,
                            "price_basis": "adj_close where available, else quoted value"},
                computed_at=now))
            out.rows += 1
            out.by_status[r.status] = out.by_status.get(r.status, 0) + 1
    session.commit()
    return out


# ------------------------------------------------------------------ read side
def aggregate(session: Session, *, storm_ids: set[str] | None = None, window: str = "0,5",
              exclude_overlap: bool = True) -> dict[str, dict]:
    """series_key -> cross-storm summary of CAR for `window` (status ok only)."""
    q = select(EventStudyResult).where(EventStudyResult.status == "ok")
    out: dict[str, dict] = {}
    rows = list(session.scalars(q))
    for r in rows:
        if storm_ids is not None and r.storm_id not in storm_ids:
            continue
        slot = out.setdefault(r.series_key, {"cars": [], "excluded_overlap": 0})
        if exclude_overlap and r.overlap:
            slot["excluded_overlap"] += 1
            continue
        slot["cars"].append(r.windows[window]["car"])
    return {k: {**es.summarize(v["cars"]), "excluded_overlap": v["excluded_overlap"], "window": window}
            for k, v in sorted(out.items())}


KEY_SERIES = ("yahoo:XOM", "yahoo:CVX", "yahoo:XLE", "eia:RWTC", "eia:RNGWHHD")
HEADLINE_WINDOW = "0,5"


def _row_dict(r: EventStudyResult, names: dict[str, str]) -> dict:
    w = (r.windows or {}).get(HEADLINE_WINDOW)
    return {"series_key": r.series_key, "name": names.get(r.series_key, r.series_key), "status": r.status,
            "detail": r.detail, "anchor": r.anchor, "anchor_date": r.anchor_date.isoformat(),
            "t0_date": r.t0_date.isoformat() if r.t0_date else None, "window": HEADLINE_WINDOW,
            "car": w["car"] if w else None, "raw_return": w["raw_return"] if w else None,
            "t_stat": w["t_stat"] if w else None, "beta": r.beta, "n_estimation": r.n_estimation,
            "vol_ratio": r.vol_ratio, "max_drawdown": r.max_drawdown, "overlap": r.overlap,
            "windows": r.windows or {}, "provenance": r.provenance or {}}


def storm_results(session: Session, storm_ids: list[str], series: tuple[str, ...] | None = KEY_SERIES) -> dict[str, list[dict]]:
    """storm_id -> event-study rows (only the requested series; all when `series` is None). Empty if never computed."""
    if not storm_ids:
        return {}
    q = select(EventStudyResult).where(EventStudyResult.storm_id.in_(storm_ids))
    if series:
        q = q.where(EventStudyResult.series_key.in_(series))
    names = {k: n for k, n in session.execute(select(MarketSeries.series_key, MarketSeries.name))}
    out: dict[str, list[dict]] = {}
    for r in session.scalars(q.order_by(EventStudyResult.series_key)):
        out.setdefault(r.storm_id, []).append(_row_dict(r, names))
    return out
