from threading import Lock

from app.schemas.common import DataMeta
from app.schemas.portfolio import (
    Holding, HoldingIn, PortfolioIn, PortfolioResponse, SectorExposure,
)
from app.services.common import now_utc

_DEFAULT = PortfolioIn(
    name="Demo Energy-Heavy Portfolio",
    total_value=1_240_000,
    holdings=[
        HoldingIn(symbol="XOM", name="ExxonMobil", sector="Energy", weight_pct=30),
        HoldingIn(symbol="CVX", name="Chevron", sector="Energy", weight_pct=20),
        HoldingIn(symbol="UNG", name="Natural Gas ETF", sector="Energy", weight_pct=15),
        HoldingIn(symbol="OTHER", name="Other assets", sector="Other", weight_pct=35),
    ],
)

# In-memory store. Phase 3 keeps it simple; PostgreSQL replaces this later
# (only this file needs to change - the API layer won't notice).
_lock = Lock()
_current: PortfolioIn = _DEFAULT
_is_user_defined = False


def _build(p: PortfolioIn, is_user: bool) -> PortfolioResponse:
    holdings = [
        Holding(
            symbol=h.symbol, name=h.name, sector=h.sector,
            weight_pct=h.weight_pct,
            value_usd=round(p.total_value * h.weight_pct / 100, 2),
        )
        for h in p.holdings
    ]
    by_sector: dict[str, float] = {}
    for h in p.holdings:
        by_sector[h.sector] = by_sector.get(h.sector, 0.0) + h.weight_pct
    exposure = [
        SectorExposure(sector=s, weight_pct=round(w, 2), value_usd=round(p.total_value * w / 100, 2))
        for s, w in sorted(by_sector.items(), key=lambda kv: -kv[1])
    ]
    meta = DataMeta(
        source="user" if is_user else "demo",
        notice=None if is_user else "Demo portfolio — stored in memory only (database comes later).",
        as_of=now_utc(),
    )
    return PortfolioResponse(
        meta=meta, name=p.name, total_value=p.total_value, holdings=holdings,
        sector_exposure=exposure, energy_exposure_pct=round(by_sector.get("Energy", 0.0), 2),
    )


def get_portfolio() -> PortfolioResponse:
    with _lock:
        return _build(_current, _is_user_defined)


def set_portfolio(p: PortfolioIn) -> PortfolioResponse:
    global _current, _is_user_defined
    with _lock:
        _current, _is_user_defined = p, True
        return _build(_current, True)


def reset_portfolio() -> None:
    global _current, _is_user_defined
    with _lock:
        _current, _is_user_defined = _DEFAULT, False
