"""Network fetchers. Each returns (payload, url); the payload is stored UNCHANGED as the raw file."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx

from app.historical.market.config import START_DATE, SeriesSpec

UA = {"User-Agent": "AEGIS-historical-ingest/1.0"}
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
EIA_URL = "https://api.eia.gov/v2/{route}/data/"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
EIA_PAGE = 5000


class MissingKey(RuntimeError):
    pass


def _get(client: httpx.Client, url: str, params: dict, tries: int = 4) -> httpx.Response:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(url, params=params, headers=UA, timeout=60)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code not in (429, 500, 502, 503, 504):
                break                                  # 4xx other than 429: retrying cannot help
        except httpx.TransportError as e:
            last = e
        time.sleep(2 ** i)
    raise RuntimeError(f"fetch failed: {type(last).__name__}: {last}") from last


def _key(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise MissingKey(f"{name} is not set")
    return v


def fetch(spec: SeriesSpec, client: httpx.Client) -> tuple[object, str]:
    """Returns (payload, url). The URL never contains an API key."""
    if spec.source == "fred":
        params = {"series_id": spec.source_series_id, "api_key": _key("FRED_API_KEY"), "file_type": "json",
                  "observation_start": START_DATE}
        return _get(client, FRED_URL, params).json(), f"{FRED_URL}?series_id={spec.source_series_id}&observation_start={START_DATE}"
    if spec.source == "eia":
        pages, offset = [], 0
        while True:
            params = {"api_key": _key("EIA_API_KEY"), "frequency": "daily", "data[0]": "value", "start": START_DATE,
                      "sort[0][column]": "period", "sort[0][direction]": "asc", "offset": offset, "length": EIA_PAGE}
            for k, v in spec.eia_facets:
                params[f"facets[{k}][]"] = v
            page = _get(client, EIA_URL.format(route=spec.eia_route), params).json()
            pages.append(page)
            rows = page.get("response", {}).get("data", [])
            total = int(page.get("response", {}).get("total", 0))
            offset += EIA_PAGE
            if not rows or offset >= total:
                break
        return pages, EIA_URL.format(route=spec.eia_route) + f"?facets[series][]={spec.source_series_id}&start={START_DATE}"
    if spec.source == "yahoo":
        p1 = int(datetime.fromisoformat(START_DATE).replace(tzinfo=timezone.utc).timestamp())
        params = {"period1": p1, "period2": int(time.time()), "interval": "1d", "events": "div,splits"}
        r = _get(client, YAHOO_URL.format(symbol=spec.source_series_id), params)
        return r.json(), YAHOO_URL.format(symbol=spec.source_series_id) + f"?period1={p1}&interval=1d"
    raise ValueError(f"unknown source {spec.source!r}")
