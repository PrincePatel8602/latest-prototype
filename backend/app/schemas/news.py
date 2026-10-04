from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import DataMeta

Sentiment = Literal["positive", "neutral", "negative"]
# How the scores were produced. "lexicon" = transparent keyword heuristic (NOT an AI model).
SentimentMethod = Literal["demo", "lexicon"]


class NewsItem(BaseModel):
    id: str
    headline: str
    publisher: str
    url: str | None = None  # link to the original article (live data only)
    published_at: datetime
    related_asset: str
    sentiment: Sentiment
    sentiment_score: float  # -1.0 (very negative) .. +1.0 (very positive)
    summary: str | None = None  # Phase 7: article description when the provider gives one


class NewsResponse(BaseModel):
    meta: DataMeta
    items: list[NewsItem]
    aggregate_score: float  # calculated: mean of item scores
    aggregate_sentiment: Sentiment
    sentiment_method: SentimentMethod


# --------------------------------------------------------------------------
# Phase 7: News Agent contract
# --------------------------------------------------------------------------
# Relevance is a transparent rule, not a probability: how many of the request's
# keyword groups (event / region / market) the article text mentions.
#   high = 2+ groups, medium = 1 group, low = none (only the provider matched it).
Relevance = Literal["high", "medium", "low"]
NewsStatus = Literal[
    "ok",          # relevant articles returned
    "no_results",  # nothing relevant found (or nothing to search for) - articles is empty
    "error",       # the agent itself failed unexpectedly (providers failing = demo fallback, see notices)
]


class NewsRequest(BaseModel):
    """What the News Agent decided to look for (derived from a ParsedQuery)."""

    event_type: str = "none"
    region: str | None = None
    sectors: list[str] = []
    assets: list[str] = []
    event_terms: list[str] = []
    region_terms: list[str] = []
    market_terms: list[str] = []
    search_query: str | None = None  # the boolean query sent to the News API (None = nothing to search)


class NewsArticle(BaseModel):
    id: str
    title: str
    source_name: str
    url: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    related_asset: str | None = None
    sentiment: Sentiment
    sentiment_score: float
    relevance: Relevance
    matched_terms: list[str] = []


class NewsIntelligence(BaseModel):
    """Structured output of the News Agent. Articles are never fabricated: they come
    from the existing News service (live NewsAPI, or the labeled simulated demo feed)."""

    # None only when no provider was queried (nothing to search for).
    meta: DataMeta | None
    status: NewsStatus
    request: NewsRequest
    articles: list[NewsArticle] = []
    aggregate_score: float | None = None
    aggregate_sentiment: Sentiment | None = None
    sentiment_method: SentimentMethod | None = None
    notices: list[str] = []
    summary: str
