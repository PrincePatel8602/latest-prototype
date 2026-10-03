"""Market Agent.

RESPONSIBILITY: decide WHICH market assets matter for a parsed question and return
their current quotes as structured, labeled data.

INPUT : ParsedQuery (intent, sectors, assets, portfolio flag).
OUTPUT: MarketIntelligence (see schemas/market.py).
TOOLS : market_service.get_market(symbols) - the EXISTING Phase 4 service
        (live Finnhub quotes, or the labeled demo table) - and portfolio_service
        (read locally, never sent anywhere) to know what the user holds.

DESIGN DECISIONS (the "why"):
* Asset selection is explicit and explainable: every asset carries `reasons`
  ("Named in your question", "Held in your portfolio", "Energy sector reference asset").
* Only ticker symbols ever reach the market provider - never weights, values or names
  of portfolios (same privacy rule as the dashboard).
* Quotes only. NO risk, volatility, correlation, history or price targets: those
  belong to the quantitative phases and are deliberately absent from the schema.
  A missing quote stays missing (available=False) - it is never estimated.
* Failure: the service already degrades to labeled demo data when the live API fails
  (the notice says so). If the agent itself breaks, it returns status="error".
"""
import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.schemas.common import DataMeta
from app.schemas.market import MarketAsset, MarketIntelligence, MarketRequest, MarketResponse, Quote
from app.schemas.query import ParsedQuery
from app.services import market_service, portfolio_service
from app.services.common import now_utc

log = logging.getLogger("finsight.agents.market")

# symbol -> (display name, kind, sector). Reference data, not market data.
_DIRECTORY: dict[str, tuple[str, str, str]] = {
    "XOM": ("ExxonMobil", "equity", "Energy"),
    "CVX": ("Chevron", "equity", "Energy"),
    "UNG": ("Natural Gas ETF", "etf", "Energy"),
    "USO": ("US Oil Fund (crude proxy)", "etf", "Energy"),
    "CL=F": ("WTI Crude Oil", "commodity", "Energy"),
    "NG=F": ("Natural Gas (Henry Hub)", "commodity", "Energy"),
}
# Reference assets used when a sector is asked about but the user holds nothing in it.
_SECTOR_REFERENCE: dict[str, list[str]] = {"Energy": ["XOM", "CVX", "UNG"]}
# Names of commodities -> acceptable symbols, best first. Free Finnhub has no futures, so the
# ETF proxy comes first; the futures symbol is only available in the demo table.
_COMMODITY_CANDIDATES: dict[str, list[str]] = {
    "crude oil": ["USO", "CL=F"], "oil": ["USO", "CL=F"], "wti": ["USO", "CL=F"], "brent": ["USO", "CL=F"],
    "natural gas": ["UNG", "NG=F"],
}
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")
_PORTFOLIO_INTENTS = {"portfolio_risk", "explain_risk", "exposure", "hedging"}
_MAX_TARGETS = 10


@dataclass
class _Target:
    """One relevant asset: acceptable symbols (best first) + why it is relevant."""

    candidates: list[str]
    name: str
    kind: str
    sector: str | None
    in_portfolio: bool = False
    reasons: list[str] = field(default_factory=list)


def _info(symbol: str) -> tuple[str, str, str | None]:
    name, kind, sector = _DIRECTORY.get(symbol, (symbol, "equity", None))
    return name, kind, sector


# --------------------------------------------------------------------------
# Step 1: decide which assets are relevant
# --------------------------------------------------------------------------
def select_targets(parsed: ParsedQuery) -> tuple[list[_Target], list[str]]:
    """ParsedQuery -> (relevant assets in priority order, notices). Reads the local portfolio only."""
    targets: dict[str, _Target] = {}   # keyed by primary symbol
    notices: list[str] = []

    def add(candidates: list[str], name: str, kind: str, sector: str | None, reason: str,
            held: bool = False) -> None:
        key = candidates[0]
        if key in targets:
            t = targets[key]
            if reason not in t.reasons:
                t.reasons.append(reason)
            t.in_portfolio = t.in_portfolio or held
        elif len(targets) < _MAX_TARGETS:
            targets[key] = _Target(candidates, name, kind, sector, held, [reason])

    holdings = [h for h in portfolio_service.get_portfolio().holdings if h.symbol != "OTHER"]
    use_portfolio = parsed.uses_portfolio or parsed.intent in _PORTFOLIO_INTENTS

    # 1) assets named in the question
    for raw in parsed.assets:
        lowered = raw.strip().lower()
        if lowered in _COMMODITY_CANDIDATES:
            cands = _COMMODITY_CANDIDATES[lowered]
            name, kind, sector = _info(cands[0])
            add(cands, name, kind, sector, "Named in your question")
        elif raw.upper() in _DIRECTORY or _TICKER.match(raw):
            sym = raw.upper()
            held = next((h for h in holdings if h.symbol == sym), None)
            name, kind, sector = _info(sym)
            add([sym], held.name if held else name, kind, held.sector if held else sector,
                "Named in your question", held=held is not None)
        else:
            notices.append(f"Could not map '{raw}' to a tradable symbol, so it was skipped.")

    # 2) the user's own holdings (all of them, or only the asked-about sectors)
    if use_portfolio:
        chosen = [h for h in holdings if not parsed.sectors or h.sector in parsed.sectors]
        for h in chosen:
            _, kind, _ = _info(h.symbol)
            add([h.symbol], h.name, kind, h.sector,
                "Held in your portfolio" + (f" ({h.sector} sector)" if parsed.sectors else ""), held=True)
        if parsed.sectors and not chosen:
            notices.append("You hold nothing in the requested sector(s): " + ", ".join(parsed.sectors)
                           + ". Showing sector reference assets instead.")

    # 3) sector reference assets when nothing in the portfolio covers the sector
    covered = {t.sector for t in targets.values()}
    for sector in parsed.sectors:
        if sector not in covered and sector in _SECTOR_REFERENCE:
            for sym in _SECTOR_REFERENCE[sector]:
                name, kind, sec = _info(sym)
                add([sym], name, kind, sec, f"{sector} sector reference asset")
    if parsed.sectors and not targets:
        notices.append("No market assets are mapped to the requested sector(s): " + ", ".join(parsed.sectors) + ".")
    return list(targets.values()), notices


# --------------------------------------------------------------------------
# Step 2: turn quotes into assets
# --------------------------------------------------------------------------
def _pair_up(targets: list[_Target]) -> list[tuple[str, str]]:
    """(symbol, name) pairs for every acceptable symbol - sent to the service as one request."""
    pairs: list[tuple[str, str]] = []
    for t in targets:
        for sym in t.candidates:
            pairs.append((sym, t.name if sym == t.candidates[0] else _info(sym)[0]))
    return pairs


def _build_assets(targets: list[_Target], response: MarketResponse) -> list[MarketAsset]:
    by_symbol: dict[str, Quote] = {q.symbol: q for q in response.quotes}
    assets: list[MarketAsset] = []
    for t in targets:
        sym = next((s for s in t.candidates if s in by_symbol), None)
        note = None
        if sym is not None and sym != t.candidates[0]:
            note = f"{sym} used because {t.candidates[0]} is not available from this data source."
        elif sym is not None and sym in ("USO",):
            note = "ETF proxy for crude oil (not futures)."
        if sym is None:
            assets.append(MarketAsset(
                symbol=t.candidates[0], name=t.name, kind=t.kind,  # type: ignore[arg-type]
                sector=t.sector, available=False, in_portfolio=t.in_portfolio, reasons=t.reasons,
                note="No quote returned for this symbol."))
            continue
        q = by_symbol[sym]
        assets.append(MarketAsset(
            symbol=q.symbol, name=q.name, kind=q.kind, sector=t.sector, available=True,
            price=q.price, change=q.change, change_pct=q.change_pct, as_of=q.as_of,
            in_portfolio=t.in_portfolio, reasons=t.reasons, note=note))
    return assets


# --------------------------------------------------------------------------
# Step 3: assemble the result
# --------------------------------------------------------------------------
def _label(meta: DataMeta | None) -> str:
    return "LIVE" if meta is not None and meta.source == "live" else "DEMO"


def analyze(parsed: ParsedQuery, targets: list[_Target], response: MarketResponse,
            notices: list[str]) -> MarketIntelligence:
    """Pure function (no I/O): selected assets + service data -> intelligence."""
    meta = response.meta
    all_notices = ([meta.notice] if meta.notice else []) + notices
    assets = _build_assets(targets, response)
    got = [a for a in assets if a.available]
    missing = [a.symbol for a in assets if not a.available]

    if not got:
        status = "no_data"
    elif missing:
        status = "partial"
        all_notices.append(f"No quote data for: {', '.join(missing)}.")
    else:
        status = "ok"
    label = _label(meta)
    summary = (f"[{label}] {len(got)} of {len(assets)} relevant asset(s) quoted: "
               + ", ".join(a.symbol for a in assets) + ".")
    if status == "no_data":
        summary = f"[{label}] No quotes available for the relevant assets: {', '.join(missing)}."
    return MarketIntelligence(
        meta=meta, status=status, request=_request(parsed, targets), assets=assets,  # type: ignore[arg-type]
        notices=all_notices, summary=summary)


def _request(parsed: ParsedQuery, targets: list[_Target]) -> MarketRequest:
    return MarketRequest(
        intent=parsed.intent, uses_portfolio=parsed.uses_portfolio, sectors=list(parsed.sectors),
        requested_assets=list(parsed.assets), symbols=[t.candidates[0] for t in targets])


def _attempted_meta(reason: str) -> DataMeta:
    live_configured = (not settings.demo_mode) and bool(settings.market_api_key)
    return DataMeta(source="live" if live_configured else "demo", notice=reason, as_of=now_utc())


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def run_market_agent(parsed: ParsedQuery) -> MarketIntelligence:
    """Never raises: provider problems become labeled demo data (service), anything else status='error'."""
    try:
        targets, notices = select_targets(parsed)
        if not targets:
            return MarketIntelligence(
                meta=None, status="no_assets", request=_request(parsed, targets),
                notices=notices + ["The question did not point to any market assets or holdings."],
                summary="No market data was requested: no relevant assets identified.")
        return analyze(parsed, targets, market_service.get_market(_pair_up(targets)), notices)
    except Exception as e:  # noqa: BLE001 - one broken agent must not crash the whole query
        log.error("market agent failed: %s", type(e).__name__)
        reason = "Market Agent failed unexpectedly; no market data is shown."
        return MarketIntelligence(
            meta=_attempted_meta(reason), status="error", request=_request(parsed, []),
            notices=[reason], summary="Market data unavailable: the Market Agent hit an error.")
