"""Read-only views of stored history for the UI's charts. Everything here comes from PostgreSQL; nothing is simulated."""
import logging
import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.historical import runtime
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.schemas.drivers import RiskDrivers
from app.schemas.query import ParsedQuery
from app.services.drivers_service import run_drivers
from app.utils.cache import TTLCache

log = logging.getLogger("aegis.insights")
router = APIRouter(prefix="/api/insights", tags=["insights"])
_cache = TTLCache()
TTL_S = 300
_GENERIC = ParsedQuery(intent="portfolio_risk", confidence=1.0, parser="rules")
_SYMBOLS = re.compile(r"^[A-Za-z0-9.\-^]{1,8}(,[A-Za-z0-9.\-^]{1,8}){0,11}$")


def _session():
    if not runtime.database_enabled():
        raise HTTPException(status_code=503, detail="Historical database is not configured (DATABASE_URL).")
    try:
        return get_sessionmaker()()
    except DatabaseNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/risk-drivers", response_model=RiskDrivers)
def risk_drivers() -> RiskDrivers:
    """Did the portfolio's risk change recently, and which holdings drive it? (cached 5 minutes; same engine as the agent)."""
    hit = _cache.get("drivers")
    if hit is not None:
        return hit
    out = run_drivers(_GENERIC)
    if out.status == "ok":
        _cache.set("drivers", out, TTL_S)
    return out


@router.get("/prices")
def prices(symbols: str = Query("XOM,CVX,UNG", description="comma-separated tickers with stored history"),
           days: int = Query(252, ge=20, le=1500)) -> dict:
    """Stored daily prices rebased to 100 at the first day shown, so different assets can be compared on one chart."""
    if not _SYMBOLS.match(symbols):
        raise HTTPException(status_code=422, detail="symbols must be 1-12 comma-separated tickers")
    from app.analytics.runner import load_prices
    from app.historical.market.models import MarketSeries
    session = _session()
    try:
        out = []
        for sym in dict.fromkeys(s.strip().upper() for s in symbols.split(",")):
            meta = session.scalar(select(MarketSeries).where(MarketSeries.series_key == f"yahoo:{sym}"))
            if meta is None:
                continue
            px = load_prices(session, meta.series_key)
            days_sorted = sorted(px)[-days:]
            if len(days_sorted) < 2:
                continue
            base = px[days_sorted[0]]
            out.append({"symbol": sym, "name": meta.name, "source": meta.source, "as_of": days_sorted[-1].isoformat(),
                        "change_pct": (px[days_sorted[-1]] / base - 1) * 100,
                        "points": [[d.isoformat(), round(px[d] / base * 100, 3)] for d in days_sorted]})
        return {"base": 100, "series": out,
                "note": "Each line is rebased to 100 on its first day shown. Prices are total-return adjusted where available."}
    except SQLAlchemyError as e:
        log.error("insights prices failed: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Price database is unreachable.") from e
    finally:
        session.close()


@router.get("/data-coverage")
def data_coverage() -> dict:
    """What the system actually holds, and how fresh it is (used on the Intelligence page)."""
    from app.analytics.models import EventStudyResult
    from app.historical.market.models import MarketObservation, MarketSeries
    from app.historical.models import HistoricalStorm, StormTrackPoint
    from app.historical.physical.models import BseeReport, BseeStormShutin
    session = _session()
    try:
        series = [{"series_key": k, "name": n, "source": s, "category": c, "first_date": f.isoformat() if f else None,
                   "last_date": l.isoformat() if l else None, "observations": o}
                  for k, n, s, c, f, l, o in session.execute(
                      select(MarketSeries.series_key, MarketSeries.name, MarketSeries.source, MarketSeries.category,
                             MarketSeries.first_date, MarketSeries.last_date, MarketSeries.n_observations).order_by(MarketSeries.series_key))]
        count = lambda col: session.scalar(select(func.count()).select_from(col)) or 0     # noqa: E731
        return {
            "storms": {"count": count(HistoricalStorm), "track_points": count(StormTrackPoint), "source": "NOAA IBTrACS v04r01 (North Atlantic, 1980 onward)"},
            "market": {"series": len(series), "observations": count(MarketObservation), "detail": series},
            "shut_ins": {"storms": count(BseeStormShutin), "reports": count(BseeReport), "source": "BSEE storm activity statistics (2011 onward)"},
            "event_study": {"results": count(EventStudyResult)},
        }
    except SQLAlchemyError as e:
        log.error("insights coverage failed: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Database is unreachable.") from e
    finally:
        session.close()
