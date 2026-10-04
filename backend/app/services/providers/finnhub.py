"""Market data adapter: Finnhub (https://finnhub.io) - free tier, US stocks & ETFs.

Endpoint used: GET /api/v1/quote?symbol=XOM  (key sent in the X-Finnhub-Token header)
Response fields we read:  c = current price, dp = day change %, t = unix time of last trade.
Finnhub answers unknown symbols with c = 0, so a zero price means "no data".

NOTE: the free tier has no futures (CL=F, NG=F). We use ETF proxies instead
(USO for crude, UNG for natural gas) and label them as proxies in the UI.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.providers.base import ProviderError, get_json

QUOTE_URL = "https://finnhub.io/api/v1/quote"


@dataclass(frozen=True)
class RawQuote:
    price: float
    change_pct: float
    as_of: datetime | None
    change: float | None = None  # Phase 7: absolute day change ("d"); None if not supplied


def parse_quote(raw: Any) -> RawQuote | None:
    """Pure function: Finnhub JSON -> RawQuote, or None if there's no usable data."""
    if not isinstance(raw, dict):
        return None
    price = raw.get("c")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    change = raw.get("dp")
    change_pct = float(change) if isinstance(change, (int, float)) else 0.0
    d = raw.get("d")
    abs_change = round(float(d), 2) if isinstance(d, (int, float)) else None
    ts = raw.get("t")
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float)) and ts > 0 else None
    return RawQuote(price=float(price), change_pct=round(change_pct, 2), as_of=as_of, change=abs_change)


def _fetch_one(symbol: str, api_key: str) -> RawQuote | None:
    raw = get_json(QUOTE_URL, headers={"X-Finnhub-Token": api_key}, params={"symbol": symbol})
    return parse_quote(raw)


def fetch_quotes(symbols: list[str], api_key: str) -> dict[str, RawQuote]:
    """Fetch several quotes in parallel. Symbols with no data are skipped.

    Raises ProviderError only if NOTHING usable came back (e.g. bad key, outage),
    so one odd symbol never breaks the whole panel.
    """
    results: dict[str, RawQuote] = {}
    errors: list[str] = []

    def work(sym: str) -> tuple[str, RawQuote | None, str | None]:
        try:
            return sym, _fetch_one(sym, api_key), None
        except ProviderError as e:
            return sym, None, str(e)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for sym, quote, err in pool.map(work, symbols):
            if quote is not None:
                results[sym] = quote
            if err is not None:
                errors.append(err)

    if not results:
        raise ProviderError(errors[0] if errors else "no quote data returned")
    return results
