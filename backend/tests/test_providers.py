"""Parsing tests for the live adapters. They use sample payloads - NO network."""
import pytest

from app.services import sentiment
from app.services.providers import finnhub, newsapi, nhc
from app.services.providers.base import ProviderError


def test_finnhub_parse_quote_ok():
    q = finnhub.parse_quote({"c": 112.4, "dp": 1.234, "t": 1_700_000_000})
    assert q and q.price == 112.4 and q.change_pct == 1.23 and q.as_of is not None


@pytest.mark.parametrize("raw", [{"c": 0, "dp": None, "t": 0}, {}, None, "oops", {"c": "x"}])
def test_finnhub_parse_quote_rejects_no_data(raw):
    assert finnhub.parse_quote(raw) is None


def test_newsapi_parse_dedupes_and_skips_removed():
    raw = {"status": "ok", "articles": [
        {"source": {"name": "A"}, "title": "Oil rises", "publishedAt": "2026-10-02T10:00:00Z", "url": "u1"},
        {"source": {"name": "B"}, "title": "oil rises", "publishedAt": "2026-10-02T11:00:00Z", "url": "u2"},
        {"source": {"name": "C"}, "title": "[Removed]", "publishedAt": "2026-10-02T11:00:00Z", "url": "u3"},
        {"source": {"name": "D"}, "title": "Bad date", "publishedAt": "nope", "url": "u4"},
    ]}
    arts = newsapi.parse_articles(raw)
    assert [a.headline for a in arts] == ["Oil rises"]


def test_newsapi_error_body_raises():
    with pytest.raises(ProviderError):
        newsapi.parse_articles({"status": "error", "code": "apiKeyInvalid"})


def test_nhc_parse_and_category():
    raw = {"activeStorms": [
        {"id": "al092026", "name": "Test", "classification": "HU", "intensity": "115",
         "latitudeNumeric": 25.5, "longitudeNumeric": -90.0, "lastUpdate": "2026-10-03T12:00:00.000Z"},
        {"id": "al102026", "name": "NoCoords", "classification": "TS", "intensity": "40"},
    ]}
    storms = nhc.parse_storms(raw)
    assert len(storms) == 1                      # malformed entry skipped
    s = storms[0]
    assert nhc.category_from_knots(s.knots) == 4  # 115 kt = Cat 4
    assert nhc.classify_region(s.lat, s.lon, s.basin) == "Gulf of Mexico"


def test_nhc_empty_storm_list_is_valid():
    assert nhc.parse_storms({"activeStorms": []}) == []


def test_nhc_bad_shape_raises():
    with pytest.raises(ProviderError):
        nhc.parse_storms({"nope": 1})


@pytest.mark.parametrize("knots,cat", [(63, 0), (64, 1), (83, 2), (96, 3), (113, 4), (137, 5)])
def test_saffir_simpson_thresholds(knots, cat):
    assert nhc.category_from_knots(knots) == cat


def test_sentiment_is_deterministic_and_directional():
    assert sentiment.score_text("Refinery shutdown and outage fears") < -0.15
    assert sentiment.score_text("Crude rallies as profit surges") > 0.15
    assert sentiment.score_text("Company announces meeting") == 0.0
    assert sentiment.score_text("Oil rallies") == sentiment.score_text("Oil rallies")


def test_related_asset_tagging():
    assert sentiment.related_asset("Exxon expands output") == "XOM"
    assert sentiment.related_asset("LNG terminals close") == "Natural gas"
    assert sentiment.related_asset("Markets wobble") == "Energy"
