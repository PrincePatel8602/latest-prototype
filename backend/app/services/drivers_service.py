"""Risk drivers: did the portfolio's risk actually change recently, and which holdings drive it?

Computed in Python from stored daily prices (PostgreSQL) and the current portfolio weights. No LLM, no forecast.
Weather / news / market results are shown as context next to the numbers, never blended into them.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import drivers as dv
from app.historical import runtime
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.schemas.common import DataMeta
from app.schemas.drivers import HoldingDriver, RiskChange, RiskDrivers, RollingPoint
from app.schemas.query import ParsedQuery
from app.services import portfolio_service
from app.services.common import now_utc
from app.services.fusion_service import _context_layers

log = logging.getLogger("aegis.drivers")
STALE_DAYS = 5
LIMITS = [
    "Volatility is measured on the holdings that have stored price history; 'Other assets' and anything without history is not covered.",
    "The Phase 10 risk score is a snapshot built from assumed volatilities, so on its own it cannot show an increase over time; "
    "the volatility comparison here uses real price history instead.",
    "This describes recent history. It does not forecast future risk.",
    "Weather, news and market layers are context only: they have no measured reliability against history here.",
]


def _empty(status: str, text: str, parsed_note: str = "") -> RiskDrivers:
    return RiskDrivers(meta=DataMeta(source="demo", notice=text, as_of=now_utc()), status=status,  # type: ignore[arg-type]
                       conclusion=text, limitations=LIMITS)


def run_drivers(parsed: ParsedQuery, *, weather=None, news=None, market=None) -> RiskDrivers:
    if not runtime.database_enabled():
        return _empty("unavailable", "Price database is not configured (DATABASE_URL); recent risk cannot be assessed.")
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured as e:
        return _empty("unavailable", str(e))
    try:
        return _assess(session, weather, news, market)
    except SQLAlchemyError as e:
        log.error("drivers database error: %s", type(e).__name__)
        return _empty("unavailable", "Price database is unreachable; recent risk cannot be assessed.")
    finally:
        session.close()


def _direction(ratio: float | None) -> str:
    if ratio is None:
        return "similar to"
    return "higher than" if ratio > 1.15 else "lower than" if ratio < 0.85 else "similar to"


def _assess(session, weather, news, market) -> RiskDrivers:
    from app.analytics.runner import load_prices
    from app.historical.market.models import MarketSeries

    pf = portfolio_service.get_portfolio()
    have = {k: c for k, c in session.execute(select(MarketSeries.series_key, MarketSeries.category))}
    weights = {h.symbol: h.weight_pct / 100 for h in pf.holdings if h.weight_pct > 0 and have.get(f"yahoo:{h.symbol}") in ("equity", "etf")}
    hhi = sum((h.weight_pct / 100) ** 2 for h in pf.holdings)
    named = [h for h in pf.holdings if h.symbol != "OTHER"] or list(pf.holdings)     # 'Other assets' is a bucket, not a position
    top = max(named, key=lambda h: h.weight_pct)
    conc = {"hhi": round(hhi, 4), "largest_position": top.symbol, "largest_position_pct": top.weight_pct,
            "energy_exposure_pct": pf.energy_exposure_pct}
    covered = sum(w * 100 for w in weights.values())
    base = dict(covered_weight_pct=round(covered, 2), uncovered_weight_pct=round(100 - covered, 2), concentration=conc,
                context_layers=_context_layers(weather, news, market, None), limitations=list(LIMITS))
    if not weights:
        return RiskDrivers(meta=DataMeta(source="demo", notice="No holdings have stored price history.", as_of=now_utc()),
                           status="insufficient_data", conclusion="None of the holdings has stored price history, so recent risk cannot be assessed.", **base)
    res = dv.analyse({s: load_prices(session, f"yahoo:{s}") for s in weights}, weights)
    if res is None:
        return RiskDrivers(meta=DataMeta(source="demo", notice="Not enough common price history.", as_of=now_utc()),
                           status="insufficient_data", conclusion=f"Fewer than {dv.MIN_DAYS} common trading days of price history; no assessment offered.", **base)

    as_of: date = res["as_of"]
    stale = (datetime.now(timezone.utc).date() - as_of).days > STALE_DAYS
    rc = RiskChange(window_days=res["recent_window_days"], recent_vol_pct=res["recent_vol_pct"], year_vol_pct=res["year_vol_pct"],
                    vol_ratio=res["vol_ratio"], history_percentile=res["history_percentile"], history_days=res["history_days"],
                    classification=res["classification"], sleeve_return_recent_pct=res["sleeve_return_recent_pct"])
    holdings = [HoldingDriver(**h) for h in sorted(res["holdings"], key=lambda h: -h["risk_share_recent_pct"])]
    lead, mover = holdings[0], max(holdings, key=lambda h: abs(h.return_recent_pct))
    verdict = {"elevated": "unusually high, so risk HAS risen versus its own history",
               "typical": "within its normal range, so there is no unusual rise in measured risk",
               "subdued": "unusually low, so risk has NOT risen"}[rc.classification]
    conclusion = (
        f"Over the last {rc.window_days} trading days the modeled holdings ({covered:.0f}% of the portfolio) had annualised volatility of "
        f"{rc.recent_vol_pct:.1f}%, {_direction(rc.vol_ratio)} the past year's {rc.year_vol_pct:.1f}%. That sits at the "
        f"{rc.history_percentile:.0f}th percentile of its own {rc.history_days // 21}-month history: {verdict}. "
        f"{lead.symbol} contributes the most to recent risk ({lead.risk_share_recent_pct:.0f}% of sleeve variance on a {lead.weight_pct:.0f}% weight); "
        f"the largest recent move was {mover.symbol} at {mover.return_recent_pct:+.1f}% over {rc.window_days} days. "
        f"Concentration: largest position {top.symbol} {top.weight_pct:.0f}%, energy exposure {pf.energy_exposure_pct:.0f}%.")
    if stale:
        conclusion += f" Note: stored prices end on {as_of.isoformat()}; run scripts/import_market.py to refresh."
    return RiskDrivers(meta=DataMeta(source="live", notice="Computed from stored daily prices (PostgreSQL) and the current portfolio.", as_of=now_utc()),
                       status="ok", prices_as_of=as_of.isoformat(), prices_stale=stale, risk_change=rc, holdings=holdings,
                       rolling_volatility=[RollingPoint(**p) for p in res["rolling_volatility"]],
                       conclusion=conclusion, **base)
