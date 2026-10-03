"""Phase 4 behaviour: live-first, demo fallback, honest labels. No real network."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import market_service, news_service, weather_service
from app.services.providers import finnhub, newsapi, nhc
from app.services.providers.base import ProviderError

client = TestClient(app)


def test_demo_mode_makes_no_external_calls(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("external call made in demo mode")
    monkeypatch.setattr(nhc, "fetch_storms", boom)
    monkeypatch.setattr(finnhub, "fetch_quotes", boom)
    for path in ("/api/weather", "/api/market", "/api/news"):
        body = client.get(path).json()
        assert body["meta"]["source"] == "demo"
        assert "Demo mode is ON" in body["meta"]["notice"]


def test_missing_key_falls_back_with_reason(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    body = client.get("/api/market").json()
    assert body["meta"]["source"] == "demo"
    assert "not configured" in body["meta"]["notice"]


def test_provider_failure_falls_back_with_exact_notice(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "market_api_key", "k")

    def fail(*a, **k):
        raise ProviderError("timeout")
    monkeypatch.setattr(finnhub, "fetch_quotes", fail)
    body = client.get("/api/market").json()
    assert body["meta"]["source"] == "demo"
    assert body["meta"]["notice"] == "Live market API unavailable — showing demo data."


def test_failure_is_cached_briefly(monkeypatch):
    """A dead API must not add a timeout to every single request."""
    monkeypatch.setattr(settings, "demo_mode", False)
    calls = {"n": 0}

    def fail():
        calls["n"] += 1
        raise ProviderError("HTTP 500")
    monkeypatch.setattr(nhc, "fetch_storms", fail)
    client.get("/api/weather"); client.get("/api/weather")
    assert calls["n"] == 1


def test_live_weather_empty_is_live_not_demo(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [])
    body = client.get("/api/weather").json()
    assert body["meta"]["source"] == "live" and body["events"] == []


def test_live_weather_gulf_storm_maps_to_energy(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    storm = nhc.RawStorm(id="al092026", name="Test", label="Hurricane", basin="atlantic",
                         knots=115, lat=25.5, lon=-90.0, last_update=None)
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm])
    ev = client.get("/api/weather").json()["events"][0]
    assert ev["category"] == 4 and ev["region"] == "Gulf of Mexico"
    assert ev["affected_sectors"] == ["Energy"] and len(ev["forecast_path"]) == 1


def test_live_non_gulf_storm_has_no_energy_chain(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    storm = nhc.RawStorm(id="al102026", name="Far", label="Tropical Storm", basin="atlantic",
                         knots=45, lat=35.0, lon=-50.0, last_update=None)
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm])
    ev = client.get("/api/weather").json()["events"][0]
    assert ev["event_type"] == "tropical_storm" and ev["affected_sectors"] == []


def test_live_market_skips_missing_symbols_and_labels_proxy(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "market_api_key", "k")
    seen = {}

    def fake(symbols, key):
        seen["symbols"] = symbols
        return {"XOM": finnhub.RawQuote(100.0, 1.5, None)}
    monkeypatch.setattr(finnhub, "fetch_quotes", fake)
    body = client.get("/api/market").json()
    assert body["meta"]["source"] == "live"
    assert [q["symbol"] for q in body["quotes"]] == ["XOM"]
    assert "OTHER" not in seen["symbols"] and "USO" in seen["symbols"]  # only tickers leave the server
    assert "proxy" in body["meta"]["notice"] and "CVX" in body["meta"]["notice"]


def test_live_news_scores_and_aggregates(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "news_api_key", "k")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    arts = [newsapi.RawArticle("Refinery shutdown looms", "A", now, "http://a"),
            newsapi.RawArticle("Crude rallies on strong demand", "B", now, "http://b")]
    monkeypatch.setattr(newsapi, "fetch_articles", lambda key, q: arts)
    body = client.get("/api/news").json()
    assert body["meta"]["source"] == "live" and body["sentiment_method"] == "lexicon"
    mean = sum(i["sentiment_score"] for i in body["items"]) / 2
    assert body["aggregate_score"] == pytest.approx(mean, abs=1e-3)


def test_errors_never_leak_keys(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "news_api_key", "SECRET-KEY-123")
    monkeypatch.setattr(newsapi, "fetch_articles", lambda k, q: (_ for _ in ()).throw(ProviderError("HTTP 401")))
    assert "SECRET-KEY-123" not in client.get("/api/news").text


# ---- LLM quota protection: cache identical questions, cool down after HTTP 429
def test_llm_answers_are_cached_and_429_triggers_a_cooldown(monkeypatch):
    from app.config import settings
    from app.services import llm_client
    from app.services.providers.base import ProviderError

    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    calls = []

    def ok(system, user, model):
        calls.append(user)
        return '{"intent": "other"}'

    monkeypatch.setattr(llm_client, "_call_gemini", ok)
    assert llm_client.complete_json("s", "same question") == {"intent": "other"}
    assert llm_client.complete_json("s", "same question") == {"intent": "other"}
    assert len(calls) == 1                                   # second identical question did not call the LLM

    def limited(system, user, model):
        calls.append(user)
        raise ProviderError("HTTP 429")

    monkeypatch.setattr(llm_client, "_call_gemini", limited)
    with pytest.raises(ProviderError):
        llm_client.complete_json("s", "another question")
    n = len(calls)
    with pytest.raises(ProviderError, match="cool-down"):
        llm_client.complete_json("s", "yet another question")
    assert len(calls) == n                                   # no call was made while cooling down


def test_llm_retries_once_on_503_but_not_on_other_errors(monkeypatch):
    from app.config import settings
    from app.services import llm_client
    from app.services.providers.base import ProviderError

    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(llm_client, "OVERLOAD_BACKOFF_S", 0)
    seq = iter([ProviderError("HTTP 503"), '{"intent": "other"}'])

    def flaky(system, user, model):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(llm_client, "_call_gemini", flaky)
    assert llm_client.complete_json("s", "q1") == {"intent": "other"}      # recovered on the retry

    n = []
    monkeypatch.setattr(llm_client, "_call_gemini", lambda s, u, m: (n.append(1), (_ for _ in ()).throw(ProviderError("HTTP 400")))[1])
    with pytest.raises(ProviderError):
        llm_client.complete_json("s", "q2")
    assert len(n) == 1                                                     # a 400 is not retried


def test_llm_falls_back_to_lighter_model_when_primary_stays_overloaded(monkeypatch):
    from app.config import settings
    from app.services import llm_client
    from app.services.providers.base import ProviderError

    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(llm_client, "OVERLOAD_BACKOFF_S", 0)
    used = []

    def call(system, user, model):
        used.append(model)
        if model == llm_client._DEFAULT_MODELS["gemini"]:
            raise ProviderError("HTTP 503")
        return '{"intent": "other"}'

    monkeypatch.setattr(llm_client, "_call_gemini", call)
    assert llm_client.complete_json("s", "q") == {"intent": "other"}
    assert used == [llm_client._DEFAULT_MODELS["gemini"]] * 2 + ["gemini-3.1-flash-lite"]
