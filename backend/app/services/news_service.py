from datetime import timedelta

from app.config import settings
from app.schemas.common import DataMeta
from app.schemas.news import NewsItem, NewsResponse
from app.services import sentiment
from app.services.common import now_utc, resolve
from app.services.providers import newsapi

# SIMULATED headlines for demo mode only. They are NOT real articles.
# (headline, related_asset, score, hours_ago)
_DEMO_ROWS = [
    ("Simulated: Gulf refinery operators review storm shutdown plans", "XOM", -0.55, 2),
    ("Simulated: LNG terminal operators prepare for possible disruption", "UNG", -0.40, 4),
    ("Simulated: Crude futures firm as offshore output at risk", "CL=F", 0.35, 5),
    ("Simulated: Analysts note energy majors' diversified operations", "CVX", 0.10, 7),
    ("Simulated: Natural gas prices jump on supply concerns", "NG=F", 0.45, 9),
]


def aggregate(items: list[NewsItem]) -> tuple[float, str]:
    """Calculated (not AI): mean of the item scores."""
    if not items:
        return 0.0, "neutral"
    avg = round(sum(i.sentiment_score for i in items) / len(items), 3)
    return avg, sentiment.label(avg)


# Kept so older imports keep working.
_aggregate = aggregate


def _demo(meta: DataMeta) -> NewsResponse:
    now = now_utc()
    items = [
        NewsItem(
            id=f"demo-news-{i}", headline=headline,
            publisher="Demo Feed (simulated)",
            published_at=now - timedelta(hours=hours),
            related_asset=asset,
            sentiment=sentiment.label(score),  # type: ignore[arg-type]
            sentiment_score=score,
        )
        for i, (headline, asset, score, hours) in enumerate(_DEMO_ROWS)
    ]
    avg, label = aggregate(items)
    return NewsResponse(meta=meta, items=items, aggregate_score=avg,
                        aggregate_sentiment=label, sentiment_method="demo")  # type: ignore[arg-type]


def _live(query: str) -> NewsResponse:
    articles = newsapi.fetch_articles(settings.news_api_key, query)
    items = []
    for i, a in enumerate(articles):
        score = sentiment.score_text(a.headline)
        items.append(NewsItem(
            id=f"live-news-{i}", headline=a.headline, publisher=a.publisher, url=a.url or None,
            published_at=a.published_at, related_asset=sentiment.related_asset(a.headline),
            summary=a.description or None,
            sentiment=sentiment.label(score), sentiment_score=score,  # type: ignore[arg-type]
        ))
    avg, label = aggregate(items)
    notice = ("Sentiment = keyword heuristic (not an AI model). "
              + ("" if items else "No matching articles found."))
    meta = DataMeta(source="live", notice=notice.strip(), as_of=now_utc())
    return NewsResponse(meta=meta, items=items, aggregate_score=avg,
                        aggregate_sentiment=label, sentiment_method="lexicon")  # type: ignore[arg-type]


def get_news(query: str | None = None) -> NewsResponse:
    # `query` is supplied by the Phase 7 News Agent; the dashboard endpoint uses the default.
    # NOTE: demo data ignores `query` (it is one fixed simulated feed); the agent filters it.
    q = query or newsapi.DEFAULT_QUERY
    return resolve(
        "news",
        live=lambda: _live(q),
        demo=_demo,
        has_key=bool(settings.news_api_key),
        cache_key=q,
        ttl_seconds=600,  # 10 min: protects the 100-requests/day free quota
    )
