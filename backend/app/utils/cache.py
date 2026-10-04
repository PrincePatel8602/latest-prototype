"""Tiny thread-safe in-memory TTL cache.

Why: free API tiers have strict quotas (NewsAPI: 100 requests/day). Without
a cache, every dashboard refresh would burn quota - and every failing API
would add a multi-second timeout to every page load.
"""
import time
from threading import Lock
from typing import Any

_MISSING = object()


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._data[key]
                return default
            return value

    def set(self, key: Any, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
