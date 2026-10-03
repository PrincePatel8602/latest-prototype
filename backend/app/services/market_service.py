import re

from app.config import settings
from app.schemas.common import DataMeta
from app.schemas.market import MarketResponse, Quote
from app.services import portfolio_service
from app.services.common import now_utc, resolve
from app.services.providers import finnhub

# ILLUSTRATIVE sample numbers - not real quotes. Labeled DEMO in every response.
_DEMO_QUOTES = [
    Quote(symbol="XOM", name="ExxonMobil", kind="equity", price=112.40, change_pct=1.2),
    Quote(symbol="CVX", name="Chevron", kind="equity", price=158.75, change_pct=0.8),
    Quote(symbol="UNG", name="Natural Gas ETF", kind="etf", price=14.20, change_pct=3.1),
    Quote(symbol="CL=F", name="WTI Crude Oil", kind="commodity", price=78.60, change_pct=2.4),
    Quote(symbol="NG=F", name="Natural Gas (Henry Hub)", kind="commodity", price=2.95, change_pct=4.0),
]

# Free Finnhub has no futures, so crude is tracked through the USO ETF (a PROXY).
_CRUDE_PROXY = ("USO", "US Oil Fund (crude proxy)")
_KNOWN_ETFS = {"UNG", "USO", "XLE", "XOP", "OIH", "VDE", "SPY", "QQQ"}
_LIVE_SYMBOL = re.compile(r"^[A-Z0-9.\-]+$")  # excludes futures-style symbols like CL=F
_MAX_SYMBOLS = 10


def _demo(meta: DataMeta) -> MarketResponse:
    return MarketResponse(meta=meta, quotes=_DEMO_QUOTES)


def _watchlist() -> list[tuple[str, str]]:
    """(symbol, display name) pairs: the user's holdings + a crude-oil proxy.

    Only ticker symbols leave our server (to the market-data provider) - never
    weights, values or the portfolio name.
    """
    pairs: dict[str, str] = {}
    for h in portfolio_service.get_portfolio().holdings:
        if h.symbol != "OTHER" and _LIVE_SYMBOL.match(h.symbol):
            pairs[h.symbol] = h.name
    pairs.setdefault(*_CRUDE_PROXY)
    return list(pairs.items())[:_MAX_SYMBOLS]


def _kind(symbol: str, name: str) -> str:
    return "etf" if symbol in _KNOWN_ETFS or "ETF" in name.upper() else "equity"


def _live(watchlist: list[tuple[str, str]]) -> MarketResponse:
    if not watchlist:  # e.g. only futures symbols were requested; the free tier cannot quote them
        return MarketResponse(
            meta=DataMeta(source="live", notice="No live-quotable symbols were requested.", as_of=now_utc()),
            quotes=[])
    raw = finnhub.fetch_quotes([s for s, _ in watchlist], settings.market_api_key)
    quotes = [
        Quote(symbol=sym, name=name, kind=_kind(sym, name),  # type: ignore[arg-type]
              price=round(raw[sym].price, 2), change_pct=raw[sym].change_pct,
              change=raw[sym].change, as_of=raw[sym].as_of)
        for sym, name in watchlist if sym in raw
    ]
    missing = [s for s, _ in watchlist if s not in raw]
    notes = ["Crude oil is shown via the USO ETF (proxy), not futures."]
    if missing:
        notes.append(f"No quote data for: {', '.join(missing)}.")
    times = [q.as_of for q in raw.values() if q.as_of]
    meta = DataMeta(source="live", notice=" ".join(notes), as_of=max(times) if times else now_utc())
    return MarketResponse(meta=meta, quotes=quotes)


def live_quotable(symbols: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep only symbols the live provider can quote (no futures-style 'CL=F'), de-duplicated."""
    seen: dict[str, str] = {}
    for sym, name in symbols:
        if _LIVE_SYMBOL.match(sym):
            seen.setdefault(sym, name)
    return list(seen.items())[:_MAX_SYMBOLS]


def get_market(symbols: list[tuple[str, str]] | None = None) -> MarketResponse:
    """Quotes for the user's watchlist, or (Phase 7 Market Agent) for specific (symbol, name) pairs.

    Demo mode always returns the same fixed demo table; the agent picks what it needs from it.
    """
    watchlist = _watchlist() if symbols is None else live_quotable(symbols)
    return resolve(
        "market",
        live=lambda: _live(watchlist),
        demo=_demo,
        has_key=bool(settings.market_api_key),
        cache_key=tuple(s for s, _ in watchlist),
        ttl_seconds=60,
    )
