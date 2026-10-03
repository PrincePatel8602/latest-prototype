"""News adapter: NewsAPI.org - free developer tier (100 requests/day, ~24h delay).

Endpoint: GET /v2/everything  (key sent in the X-Api-Key header)
Response: {"status": "ok", "articles": [{"source": {"name"}, "title", "url", "publishedAt"}]}
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.providers.base import ProviderError, get_json

EVERYTHING_URL = "https://newsapi.org/v2/everything"

# Default topic for the dashboard. Phase 7's News Agent will pass a query
# built from the user's question instead.
DEFAULT_QUERY = '"crude oil" OR "natural gas" OR refinery OR LNG OR Exxon OR Chevron'


@dataclass(frozen=True)
class RawArticle:
    headline: str
    publisher: str
    published_at: datetime
    url: str
    description: str = ""  # Phase 7: NewsAPI's short summary (may be empty)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_articles(raw: Any, limit: int = 8) -> list[RawArticle]:
    """Pure function: NewsAPI JSON -> clean, de-duplicated article list."""
    if not isinstance(raw, dict):
        raise ProviderError("unexpected response shape")
    if raw.get("status") != "ok":
        # NewsAPI error bodies carry a "code" like "apiKeyInvalid" - safe to keep.
        raise ProviderError(str(raw.get("code", "api error")))

    seen: set[str] = set()
    out: list[RawArticle] = []
    for a in raw.get("articles") or []:
        if not isinstance(a, dict):
            continue
        title = " ".join(str(a.get("title") or "").split())
        when = _parse_time(a.get("publishedAt"))
        if not title or title == "[Removed]" or when is None or title.lower() in seen:
            continue
        seen.add(title.lower())
        source = a.get("source") if isinstance(a.get("source"), dict) else {}
        out.append(RawArticle(
            headline=title,
            publisher=str(source.get("name") or "Unknown source"),
            published_at=when,
            url=str(a.get("url") or ""),
            description=" ".join(str(a.get("description") or "").split())[:400],
        ))
        if len(out) >= limit:
            break
    return out


def fetch_articles(api_key: str, query: str = DEFAULT_QUERY) -> list[RawArticle]:
    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    raw = get_json(
        EVERYTHING_URL,
        headers={"X-Api-Key": api_key},
        params={"q": query, "language": "en", "sortBy": "publishedAt",
                "pageSize": 20, "from": since},
    )
    return parse_articles(raw)
