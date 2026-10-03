import logging
from datetime import datetime, timezone
from typing import Callable, Literal, TypeVar

from app.config import settings
from app.schemas.common import DataMeta
from app.services.providers.base import ProviderError
from app.utils.cache import TTLCache

log = logging.getLogger("finsight.services")

T = TypeVar("T")
DemoReason = Literal["forced", "no_key", "unavailable"]

_cache = TTLCache()
_FAILED = object()          # marker: "live call failed recently, don't retry yet"
_FAILURE_COOLDOWN_S = 30


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def demo_meta(kind: str, reason: DemoReason = "unavailable") -> DataMeta:
    """Standard 'we are showing demo data' label. The reason tells the user WHY."""
    notice = {
        "forced": "Demo mode is ON — showing demo data (no external calls made).",
        "no_key": f"Live {kind} API not configured (no API key) — showing demo data.",
        "unavailable": f"Live {kind} API unavailable — showing demo data.",
    }[reason]
    return DataMeta(source="demo", notice=notice, as_of=now_utc())


def resolve(
    kind: str,
    *,
    live: Callable[[], T],
    demo: Callable[[DataMeta], T],
    has_key: bool = True,
    cache_key: object = None,
    ttl_seconds: float = 60,
) -> T:
    """Live-first with demo fallback. The ONE place this policy lives.

    Order: demo mode forced? -> key missing? -> cache -> live call -> demo.
    `live` must raise ProviderError on any problem. `demo` receives the
    DataMeta explaining why demo data is being shown.
    """
    if settings.demo_mode:
        return demo(demo_meta(kind, "forced"))
    if not has_key:
        return demo(demo_meta(kind, "no_key"))

    key = (kind, cache_key)
    cached = _cache.get(key)
    if cached is _FAILED:
        return demo(demo_meta(kind, "unavailable"))
    if cached is not None:
        return cached

    try:
        result = live()
    except ProviderError as e:
        # Log the safe reason only; the UI gets the generic notice.
        log.warning("live %s provider failed: %s", kind, e)
        _cache.set(key, _FAILED, _FAILURE_COOLDOWN_S)
        return demo(demo_meta(kind, "unavailable"))
    _cache.set(key, result, ttl_seconds)
    return result


def clear_cache() -> None:
    """Used by tests so one test's cached result can't leak into another."""
    _cache.clear()
