"""Phase 6: Weather Agent. NO real network: the NHC provider is always faked."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents import weather_agent
from app.agents.query_understanding import understand_query
from app.config import settings
from app.main import app
from app.schemas.query import ParsedQuery
from app.services import weather_service
from app.services.providers import nhc
from app.services.providers.base import ProviderError

client = TestClient(app)
ACCEPTANCE = "How will a Category 4 hurricane in the Gulf of Mexico affect my current energy holdings?"


# ---------------------------------------------------------------- helpers
def pq(**overrides) -> ParsedQuery:
    """The acceptance-scenario ParsedQuery, with optional overrides."""
    base = dict(intent="event_impact", event_type="hurricane", event_category=4,
                region="Gulf of Mexico", sectors=["Energy"], uses_portfolio=True,
                confidence=0.9, parser="rules")
    base.update(overrides)
    return ParsedQuery(**base)


def storm(**kw) -> nhc.RawStorm:
    base = dict(id="al092026", name="Test", label="Hurricane", basin="atlantic",
                knots=115, lat=25.5, lon=-90.0, last_update=None)
    base.update(kw)
    return nhc.RawStorm(**base)


@pytest.fixture
def live(monkeypatch):
    """DEMO_MODE=false. Individual tests then fake the provider."""
    monkeypatch.setattr(settings, "demo_mode", False)


def no_network(*a, **k):
    raise AssertionError("real network call attempted")


# ------------------------------------------------- 1. demo weather response
def test_demo_weather_response_is_the_labeled_gulf_cat4_scenario():
    body = client.get("/api/weather").json()
    assert body["meta"]["source"] == "demo" and "Demo mode is ON" in body["meta"]["notice"]
    (ev,) = body["events"]
    assert ev["category"] == 4 and ev["wind_mph"] == 130 and ev["severity"] == "HIGH"
    assert ev["region"] == "Gulf of Mexico" and ev["affected_sectors"] == ["Energy"]
    assert ev["forecast_available"] is True and len(ev["forecast_path"]) == 4
    assert "demo" in ev["data_source"].lower() and "fictional" in ev["data_source"].lower()


def test_demo_weather_is_deterministic(monkeypatch):
    monkeypatch.setattr(nhc, "get_json", no_network)
    a = client.get("/api/weather").json()["events"]
    b = client.get("/api/weather").json()["events"]
    assert a == b


# ---------------------------------------- 2. live parsing from mocked data
def test_live_provider_parsing_end_to_end_with_mocked_http(live, monkeypatch):
    raw = {"activeStorms": [{
        "id": "AL092026", "name": "Delta", "classification": "HU", "intensity": "115",
        "latitudeNumeric": 25.5, "longitudeNumeric": -90.0, "pressure": "940",
        "movementDir": 340, "movementSpeed": 10, "lastUpdate": "2026-10-03T12:00:00.000Z",
    }]}
    monkeypatch.setattr(nhc, "get_json", lambda url, **k: raw)  # fake HTTP layer
    body = client.get("/api/weather").json()
    assert body["meta"]["source"] == "live"
    assert body["meta"]["as_of"].startswith("2026-10-03T12:00:00")
    (ev,) = body["events"]
    assert ev["name"] == "Hurricane Delta" and ev["category"] == 4
    assert ev["wind_mph"] == 132                       # round(115 kt * 1.15078)
    assert ev["pressure_mb"] == 940 and ev["movement_dir_deg"] == 340
    assert ev["movement_speed_mph"] == 12              # round(10 kt * 1.15078)
    assert "NOAA" in ev["data_source"] and ev["last_update"] is not None
    # Honesty: the feed has no track, so none is invented.
    assert ev["forecast_available"] is False and len(ev["forecast_path"]) == 1


def test_live_optional_fields_stay_none_when_feed_omits_them(live, monkeypatch):
    raw = {"activeStorms": [{"id": "al012026", "name": "Bare", "classification": "TS", "intensity": "45",
                             "latitudeNumeric": 20.0, "longitudeNumeric": -60.0}]}
    monkeypatch.setattr(nhc, "get_json", lambda url, **k: raw)
    ev = client.get("/api/weather").json()["events"][0]
    assert ev["pressure_mb"] is None and ev["movement_dir_deg"] is None
    assert ev["movement_speed_mph"] is None and ev["last_update"] is None


# ------------------------------------------- 3. category / severity mapping
@pytest.mark.parametrize("knots,cat,sev", [
    (34, 0, "LOW"), (63, 0, "LOW"), (64, 1, "MODERATE"), (83, 2, "MODERATE"),
    (96, 3, "HIGH"), (113, 4, "HIGH"), (137, 5, "EXTREME"),
])
def test_category_and_severity_conversion(knots, cat, sev):
    assert nhc.category_from_knots(knots) == cat
    event = weather_service._to_event(storm(knots=knots))
    assert event.category == cat and event.severity == sev
    assert event.event_type == ("hurricane" if cat >= 1 else "tropical_storm")


# --------------------------------------------- 4. Gulf of Mexico detection
@pytest.mark.parametrize("lat,lon,basin,region", [
    (25.5, -90.0, "atlantic", "Gulf of Mexico"),
    (15.0, -70.0, "atlantic", "Caribbean Sea"),
    (35.0, -50.0, "atlantic", "Atlantic Ocean"),
    (15.0, -120.0, "east_pacific", "Eastern Pacific"),
])
def test_region_classification(lat, lon, basin, region):
    assert nhc.classify_region(lat, lon, basin) == region


def test_gulf_storm_matches_cat4_gulf_query_and_maps_to_energy(live, monkeypatch):
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm()])
    out = weather_agent.run_weather_agent(pq())
    assert out.status == "matched" and out.meta.source == "live"
    assert out.primary_event.region == "Gulf of Mexico"
    assert out.affected_sectors == ["Energy"] and out.relevant_sectors == ["Energy"]
    assert "Gulf Coast refineries" in out.affected_infrastructure
    assert out.severity == "HIGH" and out.forecast_available is False
    assert out.summary.startswith("[LIVE]")


def test_state_name_maps_to_gulf_storm(live, monkeypatch):
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm()])
    assert weather_agent.run_weather_agent(pq(region="Texas")).status == "matched"


def test_non_gulf_storm_does_not_match_gulf_query(live, monkeypatch):
    far = storm(id="al102026", label="Tropical Storm", knots=45, lat=35.0, lon=-50.0)
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [far])
    out = weather_agent.run_weather_agent(pq())
    assert out.status == "no_match" and out.primary_event is None
    assert out.events[0].match == "none" and out.events[0].region_match is False
    assert out.affected_sectors == []


def test_best_match_is_chosen_among_several_storms(live, monkeypatch):
    other = storm(id="al102026", name="Far", knots=45, lat=35.0, lon=-50.0)
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [other, storm()])
    out = weather_agent.run_weather_agent(pq())
    assert out.primary_event.id == "al092026" and len(out.events) == 2


# ------------------------------------------------------ 5. no active storm
def test_no_active_storm_is_live_and_hypothetical(live, monkeypatch):
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [])
    out = weather_agent.run_weather_agent(pq())
    assert out.status == "no_active_events" and out.primary_event is None
    assert out.meta.source == "live" and out.events == []
    assert any("hypothetical" in w for w in out.warnings)
    assert out.summary.startswith("[LIVE]")


# ------------------------------------------------ 6. provider failure fallback
@pytest.mark.parametrize("error", ["timeout", "HTTP 503", "ConnectError"])
def test_provider_failure_falls_back_to_labeled_demo(live, monkeypatch, error):
    def fail():
        raise ProviderError(error)
    monkeypatch.setattr(nhc, "fetch_storms", fail)
    assert client.get("/api/weather").status_code == 200
    out = weather_agent.run_weather_agent(pq())
    assert out.meta.source == "demo" and "unavailable" in out.meta.notice
    assert out.status == "matched"                       # demo scenario fits the demo query
    assert any(w.startswith("DEMO DATA") for w in out.warnings)


def test_malformed_provider_response_falls_back(live, monkeypatch):
    monkeypatch.setattr(nhc, "get_json", lambda url, **k: {"unexpected": True})
    body = client.get("/api/weather").json()
    assert body["meta"]["source"] == "demo"


def test_http_timeout_in_real_http_layer_falls_back(live, monkeypatch):
    def timeout(url, **k):
        raise ProviderError("timeout")   # what providers/base.py raises on httpx timeouts
    monkeypatch.setattr(nhc, "get_json", timeout)
    assert client.get("/api/weather").json()["meta"]["source"] == "demo"


def test_nonfinite_and_out_of_range_values_are_skipped_not_fatal():
    raw = {"activeStorms": [
        {"id": "al01", "name": "Nan", "intensity": "nan", "latitudeNumeric": 20, "longitudeNumeric": -60},
        {"id": "al02", "name": "Inf", "intensity": "inf", "latitudeNumeric": 20, "longitudeNumeric": -60},
        {"id": "al03", "name": "Lat", "intensity": "50", "latitudeNumeric": 999, "longitudeNumeric": -60},
        {"id": "al04", "name": "Neg", "intensity": "-5", "latitudeNumeric": 20, "longitudeNumeric": -60},
        "not-a-dict",
        {"id": "al05", "name": "Good", "intensity": "50", "latitudeNumeric": 20, "longitudeNumeric": -60},
    ]}
    assert [s.name for s in nhc.parse_storms(raw)] == ["Good"]


def test_unconvertible_provider_data_falls_back_instead_of_crashing(live, monkeypatch):
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm(knots=None)])  # type: ignore[arg-type]
    r = client.get("/api/weather")
    assert r.status_code == 200 and r.json()["meta"]["source"] == "demo"


def test_naive_timestamps_become_timezone_aware():
    t = nhc._parse_time("2026-10-03T12:00:00")
    assert t == datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def test_nhc_needs_no_api_key(live, monkeypatch):
    for key in ("market_api_key", "news_api_key", "llm_api_key"):
        assert getattr(settings, key) == ""            # conftest blanks them
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [])
    assert client.get("/api/weather").json()["meta"]["source"] == "live"


# ------------------------------------------- 7. Weather Agent + ParsedQuery
def test_agent_consumes_demo_parsed_query():
    out = weather_agent.run_weather_agent(pq())
    assert out.status == "matched" and out.meta.source == "demo"
    assert out.request.event_type == "hurricane" and out.request.event_category == 4
    assert out.request.region == "Gulf of Mexico" and out.request.sectors == ["Energy"]
    assert out.primary_event.category == 4 and out.severity == "HIGH"
    assert out.relevant_sectors == ["Energy"] and out.forecast_available is True
    assert any(w.startswith("DEMO DATA") for w in out.warnings)
    assert out.summary.startswith("[DEMO]")


def test_agent_consumes_real_query_understanding_output():
    parsed = understand_query(ACCEPTANCE).parsed
    out = weather_agent.run_weather_agent(parsed)
    assert out.status == "matched" and out.primary_event.region == "Gulf of Mexico"


def test_category_mismatch_is_a_partial_match():
    out = weather_agent.run_weather_agent(pq(event_category=3))
    assert out.status == "partial_match" and out.events[0].category_match is False
    assert out.primary_event is not None
    assert any("Requested Category 3" in w for w in out.warnings)


def test_unstated_category_and_region_do_not_constrain():
    out = weather_agent.run_weather_agent(pq(event_category=None, region=None, sectors=[]))
    assert out.status == "matched" and out.events[0].category_match is None


def test_other_region_does_not_match_demo_scenario():
    out = weather_agent.run_weather_agent(pq(region="Caribbean Sea"))
    assert out.status == "no_match" and out.primary_event is None


def test_requested_sector_with_no_mapped_impact_is_flagged():
    out = weather_agent.run_weather_agent(pq(sectors=["Technology"]))
    assert out.status == "matched" and out.relevant_sectors == []
    assert any("requested sector" in w for w in out.warnings)


def test_time_horizon_beyond_available_forecast_is_flagged_not_invented():
    long = weather_agent.run_weather_agent(pq(time_horizon="next 7 days", time_horizon_days=7))
    assert any("beyond" in w for w in long.warnings)
    ok = weather_agent.run_weather_agent(pq(time_horizon="3 days", time_horizon_days=3))
    assert not any("beyond" in w for w in ok.warnings)


def test_live_storm_with_time_horizon_says_it_cannot_be_assessed(live, monkeypatch):
    monkeypatch.setattr(nhc, "fetch_storms", lambda: [storm()])
    out = weather_agent.run_weather_agent(pq(time_horizon="next 3 days", time_horizon_days=3))
    assert any("cannot be assessed" in w for w in out.warnings)


@pytest.mark.parametrize("event", ["earthquake", "flood", "wildfire", "geopolitical", "other"])
def test_unsupported_event_type_makes_no_provider_call(monkeypatch, event):
    monkeypatch.setattr(weather_service, "get_weather", no_network)
    out = weather_agent.run_weather_agent(pq(event_type=event, supported=False, event_category=None))
    assert out.status == "unsupported_event" and out.meta is None and out.primary_event is None
    assert out.warnings


# ------------------------------------------------------- the agent endpoint
def test_analyze_endpoint_from_free_text_query():
    r = client.post("/api/weather/analyze", json={"query": ACCEPTANCE})
    assert r.status_code == 200, r.text
    body = r.json()
    p = body["parsed"]
    assert p["intent"] == "event_impact" and p["event_type"] == "hurricane"
    assert p["event_category"] == 4 and p["region"] == "Gulf of Mexico"
    assert p["sectors"] == ["Energy"] and p["uses_portfolio"] is True
    w = body["weather"]
    assert w["status"] == "matched" and w["meta"]["source"] == "demo"
    assert w["primary_event"]["category"] == 4 and w["relevant_sectors"] == ["Energy"]
    assert "Demo mode is ON" in body["parse_notice"]


def test_analyze_endpoint_accepts_already_parsed_query(monkeypatch):
    monkeypatch.setattr("app.api.weather.understand_query", no_network)  # must NOT re-parse
    r = client.post("/api/weather/analyze", json={"parsed": pq().model_dump()})
    assert r.status_code == 200 and r.json()["weather"]["status"] == "matched"
    assert r.json()["query"] is None


def test_analyze_endpoint_unsupported_event_is_200_with_status():
    r = client.post("/api/weather/analyze", json={"query": "How would an earthquake in Japan hurt my tech holdings?"})
    assert r.status_code == 200
    assert r.json()["weather"]["status"] == "unsupported_event" and r.json()["weather"]["meta"] is None


def test_analyze_endpoint_returns_no_financial_analysis():
    body = client.post("/api/weather/analyze", json={"query": ACCEPTANCE}).json()["weather"]
    forbidden = {"var", "volatility", "exposure_pct", "loss", "hedge", "hedging", "risk_score", "impact_usd"}
    assert forbidden.isdisjoint(body.keys())


@pytest.mark.parametrize("bad", [
    {}, {"query": ACCEPTANCE, "parsed": pq().model_dump()}, {"query": "ab"}, {"query": "x" * 501},
    {"parsed": {"intent": "nonsense", "confidence": 0.5, "parser": "rules"}},
])
def test_analyze_endpoint_rejects_bad_input(bad):
    assert client.post("/api/weather/analyze", json=bad).status_code == 422


def test_analyze_endpoint_falls_back_when_provider_fails(live, monkeypatch):
    def fail():
        raise ProviderError("timeout")
    monkeypatch.setattr(nhc, "fetch_storms", fail)
    r = client.post("/api/weather/analyze", json={"parsed": pq().model_dump()})
    assert r.status_code == 200 and r.json()["weather"]["meta"]["source"] == "demo"


# --------------------------------------- 8. existing /api/weather contract
def test_existing_weather_endpoint_contract_is_unchanged():
    r = client.get("/api/weather")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"meta", "events"} and body["meta"]["source"] in {"demo", "live"}
    legacy = {"id", "event_type", "name", "category", "wind_mph", "region", "lat", "lon", "forecast_path",
              "affected_regions", "affected_infrastructure", "affected_sectors", "severity"}
    assert legacy <= set(body["events"][0])
