"""Evidence fusion: what did the market actually do in comparable storms, applied to THIS portfolio?

Calibrated evidence (drives the numbers)
    PostgreSQL storms  ->  analog selection (deterministic filters from the parsed question)
    event_study_results -> 5-day abnormal return of each analog storm for each holding
    portfolio weights   -> sleeve-level distribution (arithmetic on real weights, bootstrap over storms)
Context (shown beside the numbers, never blended in)
    live weather / news / market, BSEE shut-ins, Phase 10 scenario assumptions (compared with the evidence)

No LLM, no fixed layer weights, no forecasts. If the evidence is thin the output says so instead of guessing.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import fusion as fx
from app.historical import repository as repo, runtime, settings
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.schemas.common import DataMeta
from app.schemas.fusion import (AssetEvidence, ContextLayer, DistributionStats, FusionAssessment, PortfolioEvidence, StormPoint)
from app.schemas.query import ParsedQuery
from app.services import portfolio_service
from app.services.common import now_utc
from app.services.historical_service import SUPPORTED_EVENT_TYPES, filter_from_query

log = logging.getLogger("aegis.fusion")
WINDOW = "0,5"
BASIS = "5-day cumulative abnormal return vs a S&P 500 (SPY) market model, from first Gulf entry, as % of total portfolio value"
STATIC_LIMITS = [
    "Descriptive history, not a forecast: past storms of similar strength, not a prediction for the next one.",
    "Abnormal returns are measured against SPY only; other drivers (OPEC, macro news, earnings) are not removed.",
    "Storm seasons cluster, so analog storms are not fully independent (see the independent-only sensitivity).",
    "Weather, news and market layers are shown as context only: they have no measured reliability against history here.",
]


def _unavail(parsed: ParsedQuery, status: str, text: str) -> FusionAssessment:
    return FusionAssessment(meta=DataMeta(source="demo", notice=text, as_of=now_utc()), status=status,  # type: ignore[arg-type]
                            event=_event(parsed), analogs={}, conclusion=text, limitations=STATIC_LIMITS)


def _event(p: ParsedQuery) -> dict:
    return {"event_type": p.event_type, "region": p.region, "category": p.event_category}


def _stats(values: list[float]) -> DistributionStats:
    return DistributionStats.model_validate(fx.summarize(values))


def _load_prices(session, key: str) -> dict[date, float]:
    from app.analytics.runner import load_prices
    return load_prices(session, key)


def _context_layers(weather, news, market, physical: dict | None) -> list[ContextLayer]:
    why_live = "No measured reliability against history, so it is not blended into the estimate."
    out = []
    if weather is not None:
        pe = getattr(weather, "primary_event", None)
        detail = f"{getattr(pe, 'name', '')} category {getattr(pe, 'category', 'n/a')}".strip() if pe else "no matching active event"
        out.append(ContextLayer(layer="Current weather", status=str(weather.status), summary=detail, reason=why_live))
    if news is not None:
        sc, method = news.aggregate_score, news.sentiment_method
        out.append(ContextLayer(layer="Current news", status=str(news.status), reason=why_live + " Sentiment may be a keyword heuristic.",
                                summary=f"{len(news.articles)} article(s); aggregate sentiment {news.aggregate_sentiment or 'n/a'}"
                                        f"{'' if sc is None else f' ({sc:+.2f})'}; method {method or 'n/a'}"))
    if market is not None:
        out.append(ContextLayer(layer="Current market", status=str(market.status), summary=market.summary, reason=why_live))
    if physical and physical.get("n_storms_with_bsee"):
        out.append(ContextLayer(
            layer="Physical (BSEE Gulf shut-ins, analog storms)", status="historical",
            summary=(f"{physical['n_storms_with_bsee']} of {physical['n_analogs']} analogs have BSEE data; median peak oil shut-in "
                     f"{physical['median_max_oil_shut_in_pct']:.0f}% (range {physical['min_max_oil_shut_in_pct']:.0f}-"
                     f"{physical['max_max_oil_shut_in_pct']:.0f}%)"),
            reason="Measured link between shut-in size and price response is inconsistent in this sample, so it is not used to scale the estimate."))
    return out


def run_fusion(parsed: ParsedQuery, *, weather=None, news=None, market=None, scenario=None) -> FusionAssessment:
    if parsed.event_type not in SUPPORTED_EVENT_TYPES - {"none"}:
        return _unavail(parsed, "unsupported_event",
                        "Fusion needs a specific tropical-cyclone event; the historical dataset covers tropical cyclones only.")
    if not runtime.database_enabled():
        return _unavail(parsed, "unavailable", "Historical database is not configured (DATABASE_URL); no evidence available.")
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured as e:
        return _unavail(parsed, "unavailable", str(e))
    try:
        return _assess(session, parsed, weather, news, market, scenario)
    except SQLAlchemyError as e:
        log.error("fusion database error: %s", type(e).__name__)
        return _unavail(parsed, "unavailable", "Historical database is unreachable; no evidence available.")
    finally:
        session.close()


def _assess(session, parsed: ParsedQuery, weather, news, market, scenario) -> FusionAssessment:
    from app.analytics.models import EventStudyResult
    from app.historical.market.models import MarketSeries
    from app.historical.physical.models import BseeStormShutin

    # ---------------- 1. analog storms (deterministic structured rule from the parsed question)
    f, _ = filter_from_query(parsed.event_type, parsed.region, parsed.event_category)
    c = parsed.event_category
    f.min_category, f.max_category = (max(1, c - 1), min(5, c + 1)) if c else (1, None)
    if parsed.event_type == "tropical_storm":
        f.min_category = f.max_category = None
    f.year_from, f.year_to = parsed.year_from, parsed.year_to          # a question about a past period compares that period's storms
    rule = {"event_type": f.event_type, "basin": f.basin, "gulf_only": f.gulf_only, "category_scope": f.category_scope,
            "min_category": f.min_category, "max_category": f.max_category,
            "year_from": f.year_from, "year_to": f.year_to}
    storms = repo.query_storms(session, f, limit=2000)
    ids = [s.storm_id for s in storms]
    names = {s.storm_id: f"{s.name.title()} {s.year}" for s in storms}
    years = {s.storm_id: s.year for s in storms}
    if not ids:
        return _unavail(parsed, "insufficient_evidence", "No stored historical storm matches this event description.")

    # ---------------- 2. holdings -> stored price series
    pf = portfolio_service.get_portfolio()
    have = {k: cat for k, cat in session.execute(select(MarketSeries.series_key, MarketSeries.category))}
    modeled, weights = {}, {}
    for h in pf.holdings:
        key = f"yahoo:{h.symbol}"
        if h.weight_pct > 0 and have.get(key) in ("equity", "etf"):
            modeled[h.symbol], weights[h.symbol] = key, h.weight_pct / 100
    shocks = {i.symbol: i for i in (scenario.impacts if scenario else [])}

    # ---------------- 3. per-storm abnormal returns (percent) for those holdings
    per_storm: dict[str, dict[str, float]] = {}
    overlap: dict[str, bool] = {}
    key_to_sym = {v: k for k, v in modeled.items()}
    if modeled:
        q = select(EventStudyResult).where(EventStudyResult.storm_id.in_(ids), EventStudyResult.status == "ok",
                                           EventStudyResult.series_key.in_(list(key_to_sym)))
        for r in session.scalars(q):
            w = (r.windows or {}).get(WINDOW)
            if w:
                per_storm.setdefault(r.storm_id, {})[key_to_sym[r.series_key]] = w["car"] * 100
                overlap[r.storm_id] = bool(r.overlap)

    # ---------------- 4. per-asset evidence
    assets = []
    for h in pf.holdings:
        sym = h.symbol
        series = modeled.get(sym)
        vals = [v[sym] for v in per_storm.values() if sym in v]
        st = _stats(vals) if series else None
        shock = shocks.get(sym).shock_pct if sym in shocks and shocks[sym].shock_pct else None
        assets.append(AssetEvidence(
            symbol=sym, series_key=series, weight_pct=h.weight_pct, covered=bool(series and vals), stats=st,
            scenario_shock_pct=shock, scenario_vs_history=(fx.vs_range(shock, st.p10, st.p90) if shock is not None and st else None)))

    # ---------------- 5. portfolio-level distribution over the joint sample of storms
    portfolio, joint_n = None, 0
    if weights:
        pct_w = {s: w * 100 for s, w in weights.items()}      # % per holding; sleeve contribution = sum(w_frac * car%)
        series_all = fx.portfolio_series(per_storm, weights)
        joint_n = len(series_all)
        series_ind = {sid: v for sid, v in series_all.items() if not overlap.get(sid)}
        allst, indst = _stats(list(series_all.values())), _stats(list(series_ind.values()))
        cov = sum(pct_w.values())
        sc_change = None
        if scenario:
            sc_change = sum(shocks[s].contribution_pct for s in weights if s in shocks)
        usd = (lambda v: None if v is None else round(pf.total_value * v / 100, 2))
        portfolio = PortfolioEvidence(
            per_storm=sorted((StormPoint(storm_id=sid, label=names[sid], year=years[sid], value_pct=v, independent=not overlap.get(sid))
                              for sid, v in series_all.items()), key=lambda p: p.year),
            symbols=sorted(weights), covered_weight_pct=round(cov, 2), uncovered_weight_pct=round(100 - cov, 2), basis=BASIS,
            all_analogs=allst, independent_only=indst, median_usd=usd(allst.median), p10_usd=usd(allst.p10), p90_usd=usd(allst.p90),
            scenario_change_pct=None if sc_change is None else round(sc_change, 3),
            scenario_vs_history=(fx.vs_range(sc_change, allst.p10, allst.p90) if sc_change is not None and allst.n else None))

    # ---------------- 6. physical context + real historical risk of the modeled sleeve
    bsee = list(session.scalars(select(BseeStormShutin).where(BseeStormShutin.storm_id.in_(ids), BseeStormShutin.n_reports_used > 0,
                                                              BseeStormShutin.max_oil_shut_in_pct.is_not(None))))
    physical = None
    if bsee:
        oil = [b.max_oil_shut_in_pct for b in bsee]
        physical = {"n_analogs": len(ids), "n_storms_with_bsee": len(bsee), "median_max_oil_shut_in_pct": statistics.median(oil),
                    "min_max_oil_shut_in_pct": min(oil), "max_max_oil_shut_in_pct": max(oil),
                    "source": "BSEE storm activity statistics (2011 onward)"}
    risk = None
    if weights:
        risk = fx.sleeve_risk({s: _load_prices(session, k) for s, k in modeled.items()}, weights)
        if risk:
            risk["basis"] = "daily returns of the modeled holdings weighted by portfolio weight (contribution to total portfolio)"
            risk["symbols"] = sorted(weights)

    # ---------------- 7. deterministic conclusion (rules, no LLM)
    analogs = {"selection_rule": rule, "n_selected": len(ids), "n_with_joint_results": joint_n,
               "storms": sorted(names.values())[:60], "source": "NOAA IBTrACS " + settings.SOURCE_VERSION + " + stored event study"}
    limits = list(STATIC_LIMITS)
    if portfolio and portfolio.uncovered_weight_pct:
        limits.append(f"{portfolio.uncovered_weight_pct:.0f}% of the portfolio (e.g. 'Other assets') has no stored price history and is not covered.")
    status, conclusion = "ok", ""
    if portfolio is None or portfolio.all_analogs.n < fx.MIN_N:
        n = 0 if portfolio is None else portfolio.all_analogs.n
        status = "insufficient_evidence"
        conclusion = (f"Only {n} comparable storm(s) have usable market data for these holdings (minimum {fx.MIN_N}); "
                      "no quantitative estimate is offered.")
    else:
        a, i = portfolio.all_analogs, portfolio.independent_only
        verdict = {"not_distinguishable_from_zero": "statistically indistinguishable from zero",
                   "weak_signal": "a weak signal (interval excludes zero but n<10)",
                   "indicative": "indicative (interval excludes zero)"}[a.grade]
        conclusion = (f"Across {a.n} comparable storms, the modeled holdings ({portfolio.covered_weight_pct:.0f}% of the portfolio) "
                      f"had a median 5-day abnormal return of {a.median:+.2f}% of portfolio value (10th-90th percentile {a.p10:+.2f}% to {a.p90:+.2f}%; "
                      f"about {portfolio.median_usd:+,.0f} USD median). This is {verdict}. ")
        if i.n >= fx.MIN_N:
            conclusion += f"Using only independent storms (n={i.n}) the median is {i.median:+.2f}% ({i.grade.replace('_', ' ')}). "
        else:
            conclusion += f"Only {i.n} independent storm(s) exist, too few for a separate estimate. "
        if portfolio.scenario_vs_history and portfolio.scenario_change_pct is not None:
            conclusion += (f"The Phase 10 stress assumption of {portfolio.scenario_change_pct:+.2f}% is "
                           f"{portfolio.scenario_vs_history.replace('_', ' ')}.")
    return FusionAssessment(
        meta=DataMeta(source="live", notice="Computed from stored NOAA storms, market prices and event-study results (PostgreSQL).", as_of=now_utc()),
        status=status, event=_event(parsed), analogs=analogs, window=WINDOW, assets=assets, portfolio=portfolio,
        physical_context=physical, historical_risk=risk, context_layers=_context_layers(weather, news, market, physical),
        method={"estimate": "median and 10th-90th percentile of per-storm sleeve abnormal returns; bootstrap (resampling storms) "
                            f"{int(fx.CI_LEVEL * 100)}% interval for the mean; evidence grade from sample size and interval vs zero",
                "weights": "none: portfolio weights are the user's actual weights; layers are not weighted",
                "event_study": "market model vs SPY, estimation window -250..-31 trading days, event window 0..+5"},
        conclusion=conclusion.strip(), limitations=limits)
