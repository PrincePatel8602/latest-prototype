"""News Agent.

RESPONSIBILITY: decide WHAT news is relevant to a parsed question and return
structured, labeled articles for downstream agents and the UI.

INPUT : ParsedQuery (event type, region, sectors, assets, portfolio flag).
OUTPUT: NewsIntelligence (see schemas/news.py).
TOOLS : news_service.get_news(query) - the EXISTING Phase 4 service
        (live NewsAPI.org, or the labeled simulated demo feed). This file never
        talks HTTP and there is no second News API integration.

DESIGN DECISIONS (the "why"):
* Search terms come from fixed dictionaries (event -> words, region -> words,
  sector -> words, ticker -> company name). The LLM-parsed values only SELECT from
  them or pass through a sanitised label, so nothing untrusted reaches the News API verbatim.
* Relevance is a transparent rule (how many keyword groups an article mentions),
  not a statistic. Sentiment is whatever the existing service computed
  (keyword heuristic for live news) - the agent adds no new scoring.
* Honesty: articles are never invented. The demo feed ignores the search query, so in
  DEMO mode the agent drops samples that do not mention the question's keywords.
  "Nothing relevant" is a valid, clearly-worded answer.
* Failure: the service already degrades to labeled demo data when the live API fails
  (the notice says so). If the agent itself breaks, it returns status="error".
"""
import logging
import re

from app.config import settings
from app.schemas.common import DataMeta
from app.schemas.news import NewsArticle, NewsIntelligence, NewsItem, NewsRequest, Relevance
from app.schemas.query import ParsedQuery
from app.services import news_service, portfolio_service, sentiment
from app.services.common import now_utc

log = logging.getLogger("finsight.agents.news")

# event -> (terms used in the search query, extra words only used for matching)
_EVENT_TERMS: dict[str, tuple[list[str], list[str]]] = {
    "hurricane": (["hurricane", "tropical storm"], ["cyclone", "typhoon"]),     # not bare "storm": idioms like "eye of the storm"
    "tropical_storm": (["tropical storm"], ["cyclone"]),
    "earthquake": (["earthquake"], ["seismic"]),
    "flood": (["flooding"], ["flood"]),
    "wildfire": (["wildfire"], []),
    "geopolitical": (["sanctions", "geopolitical"], ["conflict"]),
}
_REGION_TERMS: dict[str, tuple[list[str], list[str]]] = {
    "gulf of mexico": (["Gulf of Mexico", "Gulf Coast"], ["Gulf"]),
    "caribbean sea": (["Caribbean"], []),
    "atlantic ocean": (["Atlantic"], []),
    "north sea": (["North Sea"], []),
    "middle east": (["Middle East"], []),
}
_SECTOR_TERMS: dict[str, list[str]] = {
    "Energy": ["oil", "natural gas", "refinery", "LNG", "crude"],
    "Technology": ["technology stocks", "semiconductor"],
    "Financials": ["banks", "insurers"],
    "Healthcare": ["healthcare", "pharma"],
    "Industrials": ["airlines", "shipping"],
    "Utilities": ["utilities", "power grid"],
    "Consumer": ["retail", "consumer spending"],
}
_ASSET_TERMS: dict[str, list[str]] = {
    "XOM": ["Exxon"], "CVX": ["Chevron"], "UNG": ["natural gas"], "USO": ["crude oil"],
    "CL=F": ["crude oil"], "NG=F": ["natural gas"],
    "CRUDE OIL": ["crude oil"], "NATURAL GAS": ["natural gas"],
}
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")
_MAX_QUERY_CHARS = 450  # NewsAPI allows 500; keep headroom
_MAX_GROUP_TERMS = 6
_RANK = {"high": 0, "medium": 1, "low": 2}


# --------------------------------------------------------------------------
# Step 1: decide what to look for
# --------------------------------------------------------------------------
def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out


def _clean_term(term: str) -> str:
    return term.replace('"', "").replace("(", "").replace(")", "").strip()


def _boolean_query(request: NewsRequest) -> str | None:
    """Terms -> NewsAPI boolean query: (event terms) AND (region terms OR market terms)."""
    def group(terms: list[str]) -> str:
        return " OR ".join(f'"{t}"' if " " in t else t for t in terms)

    event = request.event_terms[:_MAX_GROUP_TERMS]
    where_what = _dedupe(request.region_terms + request.market_terms)[:_MAX_GROUP_TERMS + 2]
    while True:
        parts = [f"({group(g)})" for g in (event, where_what) if g]
        query = " AND ".join(parts)
        if len(query) <= _MAX_QUERY_CHARS or (len(event) <= 1 and len(where_what) <= 1):
            return query or None
        if len(where_what) > 1:
            where_what = where_what[:-1]
        else:
            event = event[:-1]


def build_request(parsed: ParsedQuery) -> NewsRequest:
    """ParsedQuery -> NewsRequest (pure function)."""
    event_terms: list[str] = []
    if parsed.event_type in _EVENT_TERMS:
        event_terms = list(_EVENT_TERMS[parsed.event_type][0])

    region_terms: list[str] = []
    if parsed.region:
        region_terms = list(_REGION_TERMS.get(parsed.region.lower(), ([_clean_term(parsed.region)], []))[0])

    market_terms: list[str] = []
    for sector in parsed.sectors:
        market_terms += _SECTOR_TERMS.get(sector, [])
    for asset in parsed.assets:
        key = asset.upper()
        if key in _ASSET_TERMS:
            market_terms += _ASSET_TERMS[key]
        elif _TICKER.match(asset):
            market_terms.append(asset)          # an unknown ticker: search the symbol itself
        else:
            market_terms.append(_clean_term(asset))

    # "my portfolio" with nothing more specific -> search for what the user holds.
    # Only names/sectors are used (never weights or values) and they stay out of the response.
    if parsed.uses_portfolio and not parsed.sectors and not parsed.assets:
        for h in portfolio_service.get_portfolio().holdings:
            if h.symbol == "OTHER":
                continue
            market_terms += _ASSET_TERMS.get(h.symbol, [_clean_term(h.name)])
            market_terms += _SECTOR_TERMS.get(h.sector, [])

    req = NewsRequest(
        event_type=parsed.event_type, region=parsed.region,
        sectors=list(parsed.sectors), assets=list(parsed.assets),
        event_terms=_dedupe(event_terms), region_terms=_dedupe(region_terms),
        market_terms=_dedupe([t for t in market_terms if t]),
    )
    req.search_query = _boolean_query(req)
    return req


# --------------------------------------------------------------------------
# Step 2: score relevance of what came back
# --------------------------------------------------------------------------
def _match_groups(request: NewsRequest) -> dict[str, list[str]]:
    """Words used to MATCH article text (search terms plus a few synonyms/tickers)."""
    event_extra = _EVENT_TERMS.get(request.event_type, ([], []))[1]
    region_extra = _REGION_TERMS.get((request.region or "").lower(), ([], []))[1]
    tickers = [a for a in request.assets if _TICKER.match(a)]
    groups = {
        "event": request.event_terms + event_extra,
        "region": request.region_terms + region_extra,
        "market": request.market_terms + tickers + [s for s in request.sectors if s != "Other"],
    }
    return {name: terms for name, terms in groups.items() if terms}


def _mentions(text: str, term: str) -> bool:
    return re.search(r"\b" + re.escape(term.lower()), text) is not None


def score_relevance(item: NewsItem, request: NewsRequest) -> tuple[Relevance, list[str]]:
    groups = _match_groups(request)
    text = f"{item.headline} {item.summary or ''}".lower()
    matched: list[str] = []
    groups_hit = 0
    # related_asset is only evidence when it is a ticker the question named; the generic
    # fallback tag ("Energy") is attached to any headline and proves nothing.
    tagged = item.related_asset.upper() in {a.upper() for a in request.assets}
    for name, terms in groups.items():
        hits = [t for t in terms if _mentions(text, t)]
        if name == "market" and tagged:
            hits.append(item.related_asset)
        if hits:
            groups_hit += 1
            matched += hits
    needed = min(2, len(groups))
    if groups_hit and groups_hit >= needed:
        level: Relevance = "high"
    elif groups_hit:
        level = "medium"
    else:
        level = "low"
    return level, _dedupe(matched)


def _to_article(item: NewsItem, request: NewsRequest) -> NewsArticle:
    level, matched = score_relevance(item, request)
    return NewsArticle(
        id=item.id, title=item.headline, source_name=item.publisher, url=item.url,
        published_at=item.published_at, summary=item.summary, related_asset=item.related_asset,
        sentiment=item.sentiment, sentiment_score=item.sentiment_score,
        relevance=level, matched_terms=matched,
    )


# --------------------------------------------------------------------------
# Step 3: assemble the result
# --------------------------------------------------------------------------
def _label(meta: DataMeta | None) -> str:
    return "LIVE" if meta is not None and meta.source == "live" else "DEMO"


def _describe(request: NewsRequest) -> str:
    bits = [request.event_type.replace("_", " ")] if request.event_terms else []
    if request.region:
        bits.append(f"in {request.region}")
    if request.sectors:
        bits.append("/".join(request.sectors) + " sector")
    elif request.assets:
        bits.append(", ".join(request.assets))
    return " ".join(bits) or "the portfolio"


def analyze(request: NewsRequest, response) -> NewsIntelligence:  # response: NewsResponse
    """Pure function (no I/O): request + News-service data -> intelligence."""
    meta = response.meta
    notices = [meta.notice] if meta.notice else []
    articles = [_to_article(i, request) for i in response.items]
    if meta.source == "demo":
        # The demo feed ignores the search query, so keep only samples that match the question.
        kept = [a for a in articles if a.relevance != "low"]
        if len(kept) < len(articles):
            notices.append("Demo feed is a fixed set of simulated energy/storm headlines; "
                           "items unrelated to the question were left out.")
        articles = kept
    articles.sort(key=lambda a: (_RANK[a.relevance], -(a.published_at.timestamp() if a.published_at else 0)))

    label = _label(meta)
    if not articles:
        return NewsIntelligence(
            meta=meta, status="no_results", request=request, articles=[], notices=notices,
            summary=f"[{label}] No relevant news found for {_describe(request)}.")

    score, sent = news_service.aggregate(
        [i for i in response.items if i.id in {a.id for a in articles}])
    return NewsIntelligence(
        meta=meta, status="ok", request=request, articles=articles, notices=notices,
        aggregate_score=score, aggregate_sentiment=sent,  # type: ignore[arg-type]
        sentiment_method=response.sentiment_method,
        summary=f"[{label}] {len(articles)} relevant article(s) for {_describe(request)}; "
                f"overall tone {sent} ({score:+.2f}, {'keyword heuristic' if response.sentiment_method == 'lexicon' else 'simulated values'}).")


def _attempted_meta(reason: str) -> DataMeta:
    """Label for the failure case: the mode we TRIED to use (never claims data we do not have)."""
    live_configured = (not settings.demo_mode) and bool(settings.news_api_key)
    return DataMeta(source="live" if live_configured else "demo", notice=reason, as_of=now_utc())


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def run_news_agent(parsed: ParsedQuery) -> NewsIntelligence:
    """Never raises: provider problems become labeled demo data (service), anything else status='error'."""
    request = build_request(parsed)
    if request.search_query is None:
        return NewsIntelligence(
            meta=None, status="no_results", request=request,
            notices=["The question did not name an event, region, sector or asset to search news for."],
            summary="No news search was run: nothing to search for.")
    try:
        return analyze(request, news_service.get_news(request.search_query))
    except Exception as e:  # noqa: BLE001 - one broken agent must not crash the whole query
        log.error("news agent failed: %s", type(e).__name__)
        reason = "News Agent failed unexpectedly; no news is shown."
        return NewsIntelligence(
            meta=_attempted_meta(reason), status="error", request=request, notices=[reason],
            summary="News unavailable: the News Agent hit an error.")
