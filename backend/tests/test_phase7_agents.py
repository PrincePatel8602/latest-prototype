"""Phase 7: News Agent + Market Agent. NO real network: every provider is faked."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents import market_agent, news_agent
from app.config import settings
from app.main import app
from app.schemas.query import ParsedQuery
from app.services import market_service, news_service, portfolio_service
from app.services.providers import finnhub, newsapi
from app.services.providers.base import ProviderError

client = TestClient(app)
ACCEPTANCE = "How will a Category 4 hurricane in the Gulf of Mexico affect my current energy holdings?"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def pq(**overrides) -> ParsedQuery:
    """The acceptance-scenario ParsedQuery, with optional overrides."""
    base = dict(intent="event_impact", event_type="hurricane", event_category=4,
                region="Gulf of Mexico", sectors=["Energy"], uses_portfolio=True,
                confidence=0.9, parser="rules")
    base.update(overrides)
    return ParsedQuery(**base)


def portfolio_pq() -> ParsedQuery:
    return ParsedQuery(intent="portfolio_risk", uses_portfolio=True, confidence=0.8, parser="rules")


def article(title="Hurricane threatens Gulf refineries", desc="Oil output at risk", pub="Reuters"):
    return newsapi.RawArticle(headline=title, publisher=pub, published_at=NOW,
                              url="https://example.com/a", description=desc)


@pytest.fixture
def live_news(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "news_api_key", "k")


@pytest.fixture
def live_market(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "market_api_key", "k")


def boom(*a, **k):
    raise AssertionError("unexpected provider call")


# ============================================================ 1. News: valid query
def test_news_request_is_built_from_event_region_sectors_assets():
    req = news_agent.build_request(pq(assets=["XOM"]))
    assert req.event_terms == ["hurricane", "tropical storm"]
    assert "Gulf of Mexico" in req.region_terms
    assert {"oil", "natural gas", "refinery"} <= set(req.market_terms) and "Exxon" in req.market_terms
    assert req.search_query.startswith('(hurricane OR "tropical storm") AND (')
    assert len(req.search_query) <= 450


def test_news_agent_demo_is_labeled_and_filtered_by_relevance():
    n = news_agent.run_news_agent(pq())
    assert n.status == "ok" and n.meta.source == "demo" and "Demo mode is ON" in n.meta.notice
    assert n.summary.startswith("[DEMO]") and n.sentiment_method == "demo"
    assert n.articles and all(a.source_name == "Demo Feed (simulated)" for a in n.articles)
    assert all(a.title.startswith("Simulated:") and a.relevance != "low" for a in n.articles)
    # best relevance first
    ranks = [{"high": 0, "medium": 1, "low": 2}[a.relevance] for a in n.articles]
    assert ranks == sorted(ranks)
    assert n.articles[0].relevance == "high" and n.articles[0].matched_terms


def test_news_agent_live_returns_structured_articles(live_news, monkeypatch):
    seen = {}

    def fake(key, q):
        seen["q"] = q
        return [article(), article("Unrelated cooking tips", "Pasta recipes")]

    monkeypatch.setattr(newsapi, "fetch_articles", fake)
    n = news_agent.run_news_agent(pq())
    assert n.meta.source == "live" and n.status == "ok" and n.summary.startswith("[LIVE]")
    assert "hurricane" in seen["q"] and "Gulf of Mexico" in seen["q"]
    a = n.articles[0]
    assert (a.title, a.source_name, a.url, a.published_at) == (
        "Hurricane threatens Gulf refineries", "Reuters", "https://example.com/a", NOW)
    assert a.summary == "Oil output at risk" and a.relevance == "high"
    assert a.sentiment in ("positive", "neutral", "negative") and -1 <= a.sentiment_score <= 1
    assert n.sentiment_method == "lexicon" and n.aggregate_sentiment is not None
    # live keeps provider results but marks the weak one as low relevance (not hidden, not invented)
    assert [x.relevance for x in n.articles] == ["high", "low"]


def test_news_portfolio_query_searches_for_holdings():
    req = news_agent.build_request(portfolio_pq())
    assert "Exxon" in req.market_terms and "Chevron" in req.market_terms and req.event_terms == []
    assert "AND" not in req.search_query


# ============================================================ 2. News: nothing relevant
def test_news_demo_nothing_relevant_returns_empty_with_notice():
    p = pq(event_type="earthquake", region="Japan", sectors=["Technology"], uses_portfolio=False)
    n = news_agent.run_news_agent(p)
    assert n.status == "no_results" and n.articles == []
    assert n.meta.source == "demo" and "No relevant news" in n.summary
    assert any("left out" in x for x in n.notices)
    assert n.aggregate_score is None  # nothing is scored when there is nothing to score


def test_news_live_empty_result(live_news, monkeypatch):
    monkeypatch.setattr(newsapi, "fetch_articles", lambda k, q: [])
    n = news_agent.run_news_agent(pq())
    assert n.status == "no_results" and n.articles == [] and n.meta.source == "live"
    assert n.summary.startswith("[LIVE] No relevant news")


def test_news_with_nothing_to_search_makes_no_call(live_news, monkeypatch):
    monkeypatch.setattr(newsapi, "fetch_articles", boom)
    n = news_agent.run_news_agent(ParsedQuery(intent="other", confidence=0.3, parser="rules"))
    assert n.status == "no_results" and n.meta is None and n.articles == []
    assert n.request.search_query is None and "nothing to search" in n.summary


# ============================================================ 3. News API failure
def test_news_api_failure_falls_back_to_labeled_demo(live_news, monkeypatch):
    def fail(k, q):
        raise ProviderError("HTTP 429")

    monkeypatch.setattr(newsapi, "fetch_articles", fail)
    n = news_agent.run_news_agent(pq())  # must not raise
    assert n.meta.source == "demo" and "unavailable" in n.meta.notice
    assert "unavailable" in " ".join(n.notices) and n.summary.startswith("[DEMO]")
    assert "429" not in n.meta.notice  # provider detail / URLs / keys never reach the UI


def test_news_agent_unexpected_error_becomes_structured_error(live_news, monkeypatch):
    def explode(q=None):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(news_service, "get_news", explode)
    n = news_agent.run_news_agent(pq())
    assert n.status == "error" and n.articles == []
    assert n.meta.source == "live"  # the mode that was attempted stays visible
    assert "secret" not in n.meta.notice and "secret" not in n.summary


# ============================================================ 4. Market: valid assets
def test_market_event_query_selects_energy_holdings_demo():
    m = market_agent.run_market_agent(pq())
    assert m.status == "ok" and m.meta.source == "demo" and m.summary.startswith("[DEMO]")
    assert [a.symbol for a in m.assets] == ["XOM", "CVX", "UNG"]
    xom = m.assets[0]
    assert (xom.name, xom.kind, xom.sector, xom.price, xom.change_pct) == ("ExxonMobil", "equity", "Energy", 112.4, 1.2)
    assert xom.in_portfolio and "Held in your portfolio (Energy sector)" in xom.reasons
    assert xom.change is None and xom.as_of is None  # demo data: nothing invented
    assert m.request.symbols == ["XOM", "CVX", "UNG"]


def test_market_live_quotes_include_change_and_timestamp(live_market, monkeypatch):
    sent = {}

    def fake(symbols, key):
        sent["symbols"] = symbols
        return {s: finnhub.RawQuote(price=100.0, change_pct=2.0, as_of=NOW, change=1.96) for s in symbols}

    monkeypatch.setattr(finnhub, "fetch_quotes", fake)
    m = market_agent.run_market_agent(pq())
    assert m.meta.source == "live" and m.summary.startswith("[LIVE]")
    assert sent["symbols"] == ["XOM", "CVX", "UNG"]  # tickers only
    a = m.assets[0]
    assert (a.price, a.change, a.change_pct, a.as_of) == (100.0, 1.96, 2.0, NOW)


def test_market_named_assets_commodity_and_unknown_symbol_are_handled():
    m = market_agent.run_market_agent(pq(uses_portfolio=False, sectors=[], assets=["Crude oil", "AAPL", "Some Company"]))
    by = {a.symbol: a for a in m.assets}
    assert m.status == "partial"
    assert by["CL=F"].available and "USO" in by["CL=F"].note  # demo table has the futures symbol only
    assert by["AAPL"].available is False and by["AAPL"].price is None
    assert any("Some Company" in n for n in m.notices) and any("No quote data for: AAPL" in n for n in m.notices)


def test_market_live_uses_etf_proxy_for_crude(live_market, monkeypatch):
    got = {}

    def fake(symbols, key):
        got["s"] = symbols
        return {s: finnhub.RawQuote(price=75.0, change_pct=-1.0, as_of=NOW) for s in symbols}

    monkeypatch.setattr(finnhub, "fetch_quotes", fake)
    m = market_agent.run_market_agent(pq(uses_portfolio=False, sectors=[], assets=["Crude oil"]))
    assert got["s"] == ["USO"]  # futures symbols are never sent to the free provider
    assert m.assets[0].symbol == "USO" and "proxy" in m.assets[0].note


def test_market_has_no_risk_fields():
    fields = set(market_agent.MarketAsset.model_fields)
    assert not fields & {"volatility", "var", "correlation", "beta", "history", "prices"}


# ============================================================ 5. Market: portfolio query
def test_market_portfolio_query_uses_all_holdings_except_placeholder():
    m = market_agent.run_market_agent(portfolio_pq())
    assert [a.symbol for a in m.assets] == ["XOM", "CVX", "UNG"]  # "OTHER" is not a tradable symbol
    assert all(a.in_portfolio for a in m.assets)


def test_market_follows_a_user_defined_portfolio(monkeypatch):
    from app.schemas.portfolio import HoldingIn, PortfolioIn
    portfolio_service.set_portfolio(PortfolioIn(name="p", total_value=1000, holdings=[
        HoldingIn(symbol="XOM", name="ExxonMobil", sector="Energy", weight_pct=50),
        HoldingIn(symbol="MSFT", name="Microsoft", sector="Technology", weight_pct=50)]))
    m = market_agent.run_market_agent(portfolio_pq())
    assert [a.symbol for a in m.assets] == ["XOM", "MSFT"]
    assert m.assets[1].available is False  # demo table has no MSFT: reported, not invented
    tech = market_agent.run_market_agent(pq(sectors=["Technology"]))
    assert [a.symbol for a in tech.assets] == ["MSFT"]


def test_market_no_assets_makes_no_call(live_market, monkeypatch):
    monkeypatch.setattr(finnhub, "fetch_quotes", boom)
    m = market_agent.run_market_agent(ParsedQuery(intent="other", confidence=0.3, parser="rules"))
    assert m.status == "no_assets" and m.meta is None and m.assets == []


# ============================================================ 6. Market API failure
def test_market_api_failure_falls_back_to_labeled_demo(live_market, monkeypatch):
    def fail(symbols, key):
        raise ProviderError("HTTP 500")

    monkeypatch.setattr(finnhub, "fetch_quotes", fail)
    m = market_agent.run_market_agent(pq())  # must not raise
    assert m.meta.source == "demo" and "unavailable" in m.meta.notice and m.summary.startswith("[DEMO]")
    assert m.status == "ok" and m.assets[0].price == 112.4


def test_market_agent_unexpected_error_becomes_structured_error(live_market, monkeypatch):
    def explode(symbols=None):
        raise RuntimeError("internal")

    monkeypatch.setattr(market_service, "get_market", explode)
    m = market_agent.run_market_agent(pq())
    assert m.status == "error" and m.assets == [] and m.meta.source == "live"
    assert "internal" not in m.meta.notice


def test_dashboard_market_endpoint_is_unchanged():
    body = client.get("/api/market").json()
    assert body["meta"]["source"] == "demo" and len(body["quotes"]) == 5


# ============================================================ endpoints
def test_news_analyze_endpoint_accepts_query_or_parsed():
    r = client.post("/api/news/analyze", json={"query": ACCEPTANCE}).json()
    assert r["parsed"]["event_type"] == "hurricane" and r["news"]["status"] == "ok"
    r2 = client.post("/api/news/analyze", json={"parsed": pq().model_dump()}).json()
    assert r2["query"] is None and r2["news"]["meta"]["source"] == "demo"
    assert client.post("/api/news/analyze", json={}).status_code == 422
    assert client.post("/api/news/analyze", json={"query": ACCEPTANCE, "parsed": pq().model_dump()}).status_code == 422


def test_market_analyze_endpoint_accepts_query_or_parsed():
    r = client.post("/api/market/analyze", json={"query": ACCEPTANCE}).json()
    assert [a["symbol"] for a in r["market"]["assets"]] == ["XOM", "CVX", "UNG"]
    r2 = client.post("/api/market/analyze", json={"parsed": portfolio_pq().model_dump()}).json()
    assert r2["market"]["status"] == "ok"
    assert client.post("/api/market/analyze", json={}).status_code == 422


def test_existing_news_endpoint_is_unchanged():
    body = client.get("/api/news").json()
    assert body["meta"]["source"] == "demo" and len(body["items"]) == 5 and body["sentiment_method"] == "demo"
