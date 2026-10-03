"""Lazy, cached accessors so the web app never needs Pinecone/PostgreSQL unless they are configured."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.historical import settings

log = logging.getLogger("aegis.historical.runtime")


def database_enabled() -> bool:
    return bool(settings.database_url()) and os.getenv("HISTORICAL_BACKEND", "auto").lower() != "local"


@lru_cache(maxsize=1)
def vector_store():
    """HistoricalVectorStore or None (not configured / unreachable). Never raises."""
    try:
        from app.historical.vector_store import connect
        return connect(create=False)
    except Exception as e:                                           # noqa: BLE001
        log.warning("Pinecone unavailable: %s: %s", type(e).__name__, e)
        return None


def reset_vector_store_cache() -> None:
    vector_store.cache_clear()
