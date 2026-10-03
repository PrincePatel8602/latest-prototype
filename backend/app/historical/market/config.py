"""Catalogue of historical market/macro series. Adding a series = adding a line here.

Sources: EIA Open Data v2 (official US spot prices), FRED (macro), Yahoo Finance chart endpoint
(equities/ETFs; an UNOFFICIAL feed, labelled as such in provenance).
"""
from __future__ import annotations

from dataclasses import dataclass

START_DATE = "1980-01-01"


@dataclass(frozen=True)
class SeriesSpec:
    key: str                  # globally unique: "<source>:<source_series_id>"
    source: str               # eia | fred | yahoo
    source_series_id: str
    name: str
    category: str             # commodity | equity | etf | macro
    unit: str
    frequency: str            # daily | monthly
    allow_negative: bool = False   # WTI printed negative in Apr-2020: a real value, not an error
    eia_route: str | None = None
    eia_facets: tuple[tuple[str, str], ...] = ()


SOURCE_NOTES = {"yahoo": "Yahoo Finance chart endpoint (unofficial, no SLA)"}

SERIES: tuple[SeriesSpec, ...] = (
    # --- EIA: official spot prices
    SeriesSpec("eia:RWTC", "eia", "RWTC", "WTI crude oil spot price (Cushing)", "commodity", "USD/barrel", "daily", True,
               "petroleum/pri/spt", (("series", "RWTC"),)),
    SeriesSpec("eia:RBRTE", "eia", "RBRTE", "Brent crude oil spot price (Europe)", "commodity", "USD/barrel", "daily", True,
               "petroleum/pri/spt", (("series", "RBRTE"),)),
    SeriesSpec("eia:RNGWHHD", "eia", "RNGWHHD", "Henry Hub natural gas spot price", "commodity", "USD/MMBtu", "daily", True,
               "natural-gas/pri/fut", (("series", "RNGWHHD"),)),
    # --- FRED: macro context
    SeriesSpec("fred:DGS10", "fred", "DGS10", "10-year Treasury constant maturity rate", "macro", "percent", "daily"),
    SeriesSpec("fred:VIXCLS", "fred", "VIXCLS", "CBOE Volatility Index (VIX) close", "macro", "index", "daily"),
    SeriesSpec("fred:DTWEXBGS", "fred", "DTWEXBGS", "Nominal broad US dollar index", "macro", "index", "daily"),
    SeriesSpec("fred:FEDFUNDS", "fred", "FEDFUNDS", "Effective federal funds rate", "macro", "percent", "monthly"),
    SeriesSpec("fred:CPIAUCSL", "fred", "CPIAUCSL", "Consumer price index, all urban consumers (SA)", "macro", "index", "monthly"),
    # --- Yahoo: equities / ETFs relevant to Gulf hurricane energy exposure
    *(SeriesSpec(f"yahoo:{t}", "yahoo", t, n, c, "USD", "daily") for t, n, c in (
        ("XOM", "Exxon Mobil", "equity"), ("CVX", "Chevron", "equity"), ("COP", "ConocoPhillips", "equity"),
        ("VLO", "Valero Energy (Gulf Coast refiner)", "equity"), ("MPC", "Marathon Petroleum", "equity"),
        ("PSX", "Phillips 66", "equity"), ("UNG", "United States Natural Gas Fund", "etf"),
        ("USO", "United States Oil Fund", "etf"), ("XLE", "Energy Select Sector SPDR", "etf"),
        ("SPY", "SPDR S&P 500 ETF (market benchmark)", "etf"))),
)
BY_KEY = {s.key: s for s in SERIES}
