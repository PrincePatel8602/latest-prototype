"""Real daily returns for the Phase 10 risk engine.

risk() already accepts a return series; until now nothing supplied one, so it fell back to assumed volatilities.
This supplies the stored daily returns (PostgreSQL) for the holdings that have price history. It returns None unless EVERY
non-"OTHER" holding has history, so the engine's all-or-nothing rule is respected and the labelled assumption fallback stays.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import drivers as dv
from app.historical import runtime
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.schemas.portfolio import PortfolioResponse

log = logging.getLogger("aegis.risk_data")
HISTORY_DAYS = 756


def real_returns(portfolio: PortfolioResponse) -> dict[str, list[float]] | None:
    symbols = [h.symbol for h in portfolio.holdings if h.symbol != "OTHER" and h.weight_pct > 0]
    if not symbols or not runtime.database_enabled():
        return None
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured:
        return None
    try:
        from app.analytics.runner import load_prices
        from app.historical.market.models import MarketSeries
        have = {k for (k,) in session.execute(select(MarketSeries.series_key))}
        if any(f"yahoo:{s}" not in have for s in symbols):
            return None
        _, rets = dv.aligned_returns({s: load_prices(session, f"yahoo:{s}") for s in symbols})
        rets = {s: v[-HISTORY_DAYS:] for s, v in rets.items()}
        return rets if rets and len(next(iter(rets.values()))) >= dv.MIN_DAYS else None
    except SQLAlchemyError as e:
        log.error("risk data unavailable: %s", type(e).__name__)
        return None
    finally:
        session.close()
