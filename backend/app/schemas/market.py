from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import DataMeta


class Quote(BaseModel):
    symbol: str
    name: str
    kind: Literal["equity", "etf", "commodity"]
    price: float
    change_pct: float  # day change in percent
    # Phase 7 (optional, additive): only filled when the provider supplies them - never guessed.
    change: float | None = None     # absolute day change
    as_of: datetime | None = None   # provider's last-trade time


class MarketResponse(BaseModel):
    meta: DataMeta
    quotes: list[Quote]


# --------------------------------------------------------------------------
# Phase 7: Market Agent contract (quotes only - no risk, volatility or history)
# --------------------------------------------------------------------------
MarketStatus = Literal[
    "ok",          # every relevant asset has a quote
    "partial",     # some relevant assets have no quote
    "no_data",     # relevant assets were identified but none returned a quote
    "no_assets",   # the question did not point to any market assets
    "error",       # the agent itself failed unexpectedly
]


class MarketRequest(BaseModel):
    intent: str
    uses_portfolio: bool = False
    sectors: list[str] = []
    requested_assets: list[str] = []  # as named in the question
    symbols: list[str] = []           # the symbols the agent decided are relevant


class MarketAsset(BaseModel):
    symbol: str
    name: str
    kind: Literal["equity", "etf", "commodity"]
    sector: str | None = None
    available: bool                    # False = no quote returned for this symbol
    price: float | None = None
    change: float | None = None        # absolute day change (only if the provider supplies it)
    change_pct: float | None = None
    as_of: datetime | None = None      # quote timestamp (None for demo data / not supplied)
    in_portfolio: bool = False
    reasons: list[str] = []            # why this asset is relevant to the question
    note: str | None = None            # e.g. "proxy for crude oil"


class MarketIntelligence(BaseModel):
    # None only when no provider was queried (nothing to search for).
    meta: DataMeta | None
    status: MarketStatus
    request: MarketRequest
    assets: list[MarketAsset] = []
    notices: list[str] = []
    summary: str
