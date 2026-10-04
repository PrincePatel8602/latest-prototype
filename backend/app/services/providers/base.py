"""Shared HTTP helper for all live data providers.

Two security rules enforced here:
1. API keys are sent in HEADERS, never in the URL. httpx error messages
   include the URL, so a key in the query string could leak into logs.
2. Every failure becomes a ProviderError with a SAFE message (no URL, no key).
"""
from typing import Any

import httpx

TIMEOUT_SECONDS = 6.0  # a slow API must not freeze the dashboard


class ProviderError(Exception):
    """Raised when a live provider cannot give us usable data."""


def _request(method: str, url: str, *, timeout: float, **kwargs: Any) -> Any:
    try:
        resp = httpx.request(method, url, timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"HTTP {e.response.status_code}") from None
    except httpx.TimeoutException:
        raise ProviderError("timeout") from None
    except (httpx.HTTPError, ValueError) as e:
        # ValueError = body was not valid JSON. Only the exception TYPE is kept.
        raise ProviderError(type(e).__name__) from None


def get_json(url: str, *, headers: dict[str, str] | None = None,
             params: dict[str, Any] | None = None) -> Any:
    return _request("GET", url, timeout=TIMEOUT_SECONDS, headers=headers, params=params)


def post_json(url: str, *, headers: dict[str, str], body: dict[str, Any],
              timeout: float = 20.0) -> Any:
    """POST JSON. LLM calls get a longer timeout than data lookups."""
    return _request("POST", url, timeout=timeout, headers=headers, json=body)
