import json
import time
from typing import Any

from app.config import settings
from app.services.providers.base import ProviderError, post_json

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.8-flash",
}


# Free-tier LLM keys have tiny daily quotas. Identical questions reuse the last successful answer, and after an
# HTTP 429 the LLM is skipped for a cool-down so every request does not burn a call (or wait) on a known failure.
_CACHE: dict[tuple, dict[str, Any]] = {}
_CACHE_MAX = 128
RATE_LIMIT_COOLDOWN_S = 600
OVERLOAD_RETRIES = 1
OVERLOAD_BACKOFF_S = 1.5
_blocked_until = 0.0


def reset_state() -> None:
    """Clear the answer cache and the rate-limit cool-down (used by tests)."""
    global _blocked_until
    _CACHE.clear()
    _blocked_until = 0.0


# If the primary model stays overloaded (HTTP 503) after the retry, try this lighter model once.
_FALLBACK_MODELS = {"gemini": "gemini-3.1-flash-lite"}


def active_model() -> str:
    return settings.llm_model or _DEFAULT_MODELS.get(
        settings.llm_provider.lower(), ""
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first {...} object out of an LLM reply."""
    start, end = text.find("{"), text.rfind("}")

    if start == -1 or end <= start:
        raise ProviderError("LLM reply contained no JSON object")

    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise ProviderError("LLM reply was not valid JSON") from None

    if not isinstance(data, dict):
        raise ProviderError("LLM JSON was not an object")

    return data


def _call_anthropic(system: str, user: str, model: str) -> str:
    data = post_json(
        _ANTHROPIC_URL,
        headers={
            "x-api-key": settings.llm_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        body={
            "model": model,
            "max_tokens": 700,
            "temperature": 0,
            "system": system,
            "messages": [
                {"role": "user", "content": user}
            ],
        },
    )

    blocks = data.get("content") if isinstance(data, dict) else None

    if not isinstance(blocks, list):
        raise ProviderError("unexpected Anthropic response shape")

    return "".join(
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "text"
    )


def _call_openai(system: str, user: str, model: str) -> str:
    data = post_json(
        _OPENAI_URL,
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "content-type": "application/json",
        },
        body={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )

    try:
        return str(
            data["choices"][0]["message"]["content"] or ""
        )
    except (KeyError, IndexError, TypeError):
        raise ProviderError(
            "unexpected OpenAI response shape"
        ) from None


def _call_gemini(system: str, user: str, model: str) -> str:
    """Call Google Gemini generateContent API."""

    url = (
        f"https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )

    data = post_json(
        url,
        headers={
            "x-goog-api-key": settings.llm_api_key,
            "content-type": "application/json",
        },
        body={
            "systemInstruction": {
                "parts": [
                    {"text": system}
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": user}
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        },
    )

    try:
        candidates = data["candidates"]

        if not candidates:
            raise ProviderError("Gemini returned no candidates")

        parts = candidates[0]["content"]["parts"]

        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
        )

        if not text:
            raise ProviderError("Gemini returned empty text")

        return text

    except ProviderError:
        raise

    except (KeyError, IndexError, TypeError):
        raise ProviderError(
            "unexpected Gemini response shape"
        ) from None


def complete_json(system: str, user: str) -> dict[str, Any]:
    """Ask the configured LLM for a JSON object."""
    global _blocked_until

    provider = settings.llm_provider.lower()
    model = active_model()

    if not settings.llm_api_key:
        raise ProviderError("LLM_API_KEY is not configured")

    key = (provider, model, system, user)
    if key in _CACHE:
        return dict(_CACHE[key])

    if time.monotonic() < _blocked_until:
        raise ProviderError("HTTP 429 (LLM rate-limited; skipped during cool-down)")

    calls = {"anthropic": _call_anthropic, "openai": _call_openai, "gemini": _call_gemini}
    if provider not in calls:
        raise ProviderError(f"unknown LLM_PROVIDER '{settings.llm_provider}'")
    for attempt in range(OVERLOAD_RETRIES + 1):
        try:
            text = calls[provider](system, user, model)
            break
        except ProviderError as e:
            if "429" in str(e):
                _blocked_until = time.monotonic() + RATE_LIMIT_COOLDOWN_S
                raise
            if "503" in str(e) and attempt < OVERLOAD_RETRIES:      # provider briefly overloaded: one short retry
                time.sleep(OVERLOAD_BACKOFF_S)
                continue
            fallback = _FALLBACK_MODELS.get(provider)
            if "503" in str(e) and fallback and fallback != model:
                text = calls[provider](system, user, fallback)      # still overloaded: one try on the lighter model
                break
            raise

    result = extract_json_object(text)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = result
    return dict(result)
