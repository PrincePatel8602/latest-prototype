"""Hedging analysis: which instruments would have reduced this portfolio's risk historically, and how well do they hold up?

Everything is measured from stored daily prices and the stored hurricane event-study windows (PostgreSQL):
  * candidate hedges are fixed, liquid instruments we hold price history for (SPY, XLE, USO)
  * the hedge ratio is the minimum-variance beta; ranking is by OUT-OF-SAMPLE variance reduction
  * each hedge is also replayed through comparable hurricane windows (when the question names a storm event)
Costs, margin, borrow, taxes, options and liquidity are NOT modelled and are listed as such. No LLM, no recommendation to trade.
"""
from __future__ import annotations

import logging
from bisect import bisect_left
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import drivers as dv, hedging as hg
from app.historical import repository as repo, runtime
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.schemas.common import DataMeta
from app.schemas.hedging import HedgeCandidate, HedgingAnalysis, TrimOption
from app.schemas.query import ParsedQuery
from app.services import portfolio_service
from app.services.common import now_utc
from app.services.historical_service import SUPPORTED_EVENT_TYPES, filter_from_query

log = logging.getLogger("aegis.hedging")
CANDIDATES = (("yahoo:SPY", "S&P 500 (SPY)", "market"), ("yahoo:XLE", "Energy sector (XLE)", "sector"), ("yahoo:USO", "Crude oil (USO)", "commodity"))
HISTORY_DAYS = 756
TRIMS = (0.25, 0.5)
NOT_MODELED = [
    "Trading costs, bid-ask spreads, ETF fees, margin and borrow costs for shorting.",
    "Options (puts, collars): no option price history is stored, so none are evaluated.",
    "Taxes, liquidity and execution; position limits.",
    "Basis risk that changes in the future: hedge ratios are estimated from the past and drift.",
]
LIMITS = [
    "Historical and descriptive, not investment advice or a recommendation to trade.",
    "Only holdings with stored price history are hedged ('Other assets' is not covered).",
    "A hedge that reduced variance in the past can fail in a new regime; the out-of-sample figure shows how stable it was.",
]


def _empty(status: str, text: str) -> HedgingAnalysis:
    return HedgingAnalysis(meta=DataMeta(source="demo", notice=text, as_of=now_utc()), status=status,  # type: ignore[arg-type]
                           conclusion=text, not_modeled=NOT_MODELED, limitations=LIMITS)


def run_hedging(parsed: ParsedQuery, *, risk=None) -> HedgingAnalysis:
    if not runtime.database_enabled():
        return _empty("unavailable", "Price database is not configured (DATABASE_URL); hedges cannot be evaluated.")
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured as e:
        return _empty("unavailable", str(e))
    try:
        return _assess(session, parsed)
    except SQLAlchemyError as e:
        log.error("hedging database error: %s", type(e).__name__)
        return _empty("unavailable", "Price database is unreachable; hedges cannot be evaluated.")
    finally:
        session.close()


def _window_return(prices: dict[date, float], t0: date, days: int = 5) -> float | None:
    """Return from the close before t0 to the close `days` trading days after t0 (matches the event-study window 0..days)."""
    d = sorted(prices)
    i0 = bisect_left(d, t0)
    if i0 < 1 or i0 + days >= len(d):
        return None
    return prices[d[i0 + days]] / prices[d[i0 - 1]] - 1


def _storm_returns(session, parsed: ParsedQuery, modeled: dict[str, str], hedge_keys: list[str], prices_of) -> tuple[dict, dict, dict]:
    """-> (per_storm raw 5-day returns {sid: {series_key: r}}, analog info). Empty when no supported storm event."""
    from app.analytics.models import EventStudyResult
    if parsed.event_type not in SUPPORTED_EVENT_TYPES - {"none"}:
        return {}, {}, {}
    f, _ = filter_from_query(parsed.event_type, parsed.region, parsed.event_category)
    c = parsed.event_category
    f.min_category, f.max_category = (max(1, c - 1), min(5, c + 1)) if c else (1, None)
    ids = [s.storm_id for s in repo.query_storms(session, f, limit=2000)]
    keys = list(modeled.values()) + [k for k in hedge_keys if k != "yahoo:SPY"]
    per: dict[str, dict[str, float]] = {}
    t0s: dict[str, date] = {}
    q = select(EventStudyResult).where(EventStudyResult.storm_id.in_(ids), EventStudyResult.status == "ok", EventStudyResult.series_key.in_(keys))
    for r in session.scalars(q):
        w = (r.windows or {}).get("0,5")
        if w:
            per.setdefault(r.storm_id, {})[r.series_key] = w["raw_return"]
            t0s[r.storm_id] = r.t0_date
    if "yahoo:SPY" in hedge_keys:
        spy = prices_of("yahoo:SPY")
        for sid, t0 in t0s.items():
            r = _window_return(spy, t0)
            if r is not None:
                per[sid]["yahoo:SPY"] = r
    return per, {"n_analogs_selected": len(ids), "selection_rule": {"event_type": f.event_type, "gulf_only": f.gulf_only,
                                                                    "min_category": f.min_category, "max_category": f.max_category}}, t0s


def _assess(session, parsed: ParsedQuery) -> HedgingAnalysis:
    from app.analytics.runner import load_prices
    from app.historical.market.models import MarketSeries

    pf = portfolio_service.get_portfolio()
    have = {k: c for k, c in session.execute(select(MarketSeries.series_key, MarketSeries.category))}
    weights = {h.symbol: h.weight_pct / 100 for h in pf.holdings if h.weight_pct > 0 and have.get(f"yahoo:{h.symbol}") in ("equity", "etf")}
    if not weights:
        return _empty("insufficient_data", "None of the holdings has stored price history, so hedges cannot be evaluated.")
    cache: dict[str, dict[date, float]] = {}

    def prices_of(key: str) -> dict[date, float]:
        if key not in cache:
            cache[key] = load_prices(session, key)
        return cache[key]

    modeled = {s: f"yahoo:{s}" for s in weights}
    sleeve_pct = sum(weights.values()) * 100
    sleeve_usd = pf.total_value * sum(weights.values())
    hedge_keys = [k for k, _, _ in CANDIDATES if have.get(k)]

    # ---- storm windows (optional): hedge replayed through comparable hurricanes
    per_storm, info, _ = _storm_returns(session, parsed, modeled, hedge_keys, prices_of)

    candidates: list[HedgeCandidate] = []
    for key, name, kind in CANDIDATES:
        if key not in hedge_keys:
            candidates.append(HedgeCandidate(series_key=key, name=name, kind=kind, status="insufficient_history", note="no stored price history"))
            continue
        # a symbol that is itself a hedge instrument and a holding (e.g. XLE held) is allowed; the sleeve is the whole modeled book
        dates, rets = dv.aligned_returns({**{s: prices_of(k) for s, k in modeled.items()}, "__h": prices_of(key)})
        dates, rets = dates[-HISTORY_DAYS:], {s: v[-HISTORY_DAYS:] for s, v in rets.items()}
        if len(dates) < hg.MIN_DAYS:
            candidates.append(HedgeCandidate(series_key=key, name=name, kind=kind, status="insufficient_history",
                                             note=f"only {len(dates)} common trading days with the holdings (need {hg.MIN_DAYS})"))
            continue
        rs = dv.sleeve_series({s: rets[s] for s in weights}, weights)
        ev = hg.evaluate(rs, rets["__h"])
        beta = ev["hedge_ratio"]
        sw = None
        if per_storm:
            sleeve = {sid: sum(weights[s] * v[modeled[s]] for s in weights) for sid, v in per_storm.items() if all(modeled[s] in v for s in weights)}
            hedge = {sid: v[key] for sid, v in per_storm.items() if key in v}
            sw = hg.storm_windows(sleeve, hedge, beta)
        candidates.append(HedgeCandidate(
            series_key=key, name=name, kind=kind, status="ok", position="short" if beta >= 0 else "long", hedge_ratio=beta,
            notional_usd=abs(beta) * pf.total_value, notional_pct_of_portfolio=abs(beta) * 100, correlation=ev["correlation"],
            in_sample_variance_reduction_pct=ev["in_sample_variance_reduction_pct"], out_of_sample=ev["out_of_sample"],
            before=ev["before"], after=ev["after"], storm_windows=sw,
            note=f"{ev['days']} trading days ({dates[0]} to {dates[-1]})"))
    ok = sorted((c for c in candidates if c.status == "ok"), key=lambda c: -c.out_of_sample["variance_reduction_pct"])
    for i, c in enumerate(ok, start=1):
        c.rank = i
    candidates.sort(key=lambda c: (c.rank is None, c.rank or 0))

    # ---- trimming the biggest risk contributor
    dates, rets = dv.aligned_returns({s: prices_of(k) for s, k in modeled.items()})
    rets = {s: v[-HISTORY_DAYS:] for s, v in rets.items()}
    trims: list[TrimOption] = []
    if len(next(iter(rets.values()))) >= dv.MIN_DAYS:
        shares = dv.variance_shares(rets, weights, dv.RECENT)
        top = max(shares, key=shares.get)
        trims = [TrimOption(**hg.trim_effect(rets, weights, top, f)) for f in TRIMS]

    if not ok:
        return HedgingAnalysis(meta=DataMeta(source="demo", notice="Not enough common history.", as_of=now_utc()), status="insufficient_data",
                               candidates=candidates, trim_options=trims, not_modeled=NOT_MODELED, limitations=LIMITS,
                               conclusion="No candidate hedge has enough common price history with the holdings; none can be evaluated.")
    best = ok[0]
    oos = best.out_of_sample
    if oos["variance_reduction_pct"] <= 0:
        return HedgingAnalysis(meta=DataMeta(source="live", notice="Computed from stored daily prices (PostgreSQL).", as_of=now_utc()), status="ok",
                               basis={"history_days": HISTORY_DAYS, "sleeve_weight_pct": round(sleeve_pct, 2)}, candidates=candidates,
                               trim_options=trims, storm_context=info or None, not_modeled=NOT_MODELED, limitations=LIMITS,
                               conclusion="None of the candidate hedges (SPY, XLE, USO) reduced the modeled holdings' variance out of sample; "
                                          "no hedge is supported by the history. Costs, options and taxes are not modeled.")
    conclusion = (
        f"Of the instruments with stored history, {best.name} historically removed the most risk from the modeled holdings "
        f"({sleeve_pct:.0f}% of the portfolio): a short of about {best.notional_pct_of_portfolio:.0f}% of portfolio value "
        f"(~{best.notional_usd:,.0f} USD) cut variance by {best.in_sample_variance_reduction_pct:.0f}% in-sample and "
        f"{oos['variance_reduction_pct']:.0f}% out-of-sample (tested on the latest {oos['test_days']} days). "
        f"Volatility went from {best.before['volatility_pct']:.1f}% to {best.after['volatility_pct']:.1f}% and the worst day from "
        f"{best.before['worst_day_pct']:.1f}% to {best.after['worst_day_pct']:.1f}%; the remainder is basis risk the hedge cannot remove. ")
    sw = best.storm_windows
    if sw and sw["n"] >= 3:
        u, h = sw["unhedged"], sw["hedged"]
        effects = []
        if (h["p90"] - h["p10"]) < (u["p90"] - u["p10"]):
            effects.append("narrowed the range of outcomes")
        else:
            effects.append("did not narrow the range of outcomes")
        if h["p90"] < u["p90"]:
            effects.append("gave up some of the upside")
        if h["p10"] > u["p10"]:
            effects.append("limited the downside")
        conclusion += (f"In {sw['n']} comparable hurricane windows the 5-day outcome moved from a median of {u['median']:+.2f}% "
                       f"(10th-90th {u['p10']:+.2f}% to {u['p90']:+.2f}%) to {h['median']:+.2f}% ({h['p10']:+.2f}% to {h['p90']:+.2f}%): "
                       f"the hedge {', '.join(effects)}. ")
    if trims:
        t = trims[0]
        conclusion += (f"As a non-derivative alternative, trimming {t.symbol} by {int(t.trim_fraction * 100)}% would have cut the sleeve's volatility "
                       f"by {t.volatility_reduction_pct:.0f}% ({t.volatility_before_pct:.1f}% to {t.volatility_after_pct:.1f}%). ")
    conclusion += "Costs, options and taxes are not modeled."
    return HedgingAnalysis(
        meta=DataMeta(source="live", notice="Computed from stored daily prices and stored hurricane event windows (PostgreSQL).", as_of=now_utc()),
        status="ok", basis={"history_days": HISTORY_DAYS, "sleeve_weight_pct": round(sleeve_pct, 2), "sleeve_value_usd": round(sleeve_usd, 2),
                            "total_value_usd": pf.total_value, "ranking_rule": "out-of-sample variance reduction (hedge ratio estimated on older data, tested on the latest year)"},
        candidates=candidates, trim_options=trims, storm_context=info or None, not_modeled=NOT_MODELED, conclusion=conclusion, limitations=LIMITS)
