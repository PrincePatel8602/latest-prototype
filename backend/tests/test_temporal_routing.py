"""A question about a past period is answered from the historical record only; non-portfolio questions skip portfolio maths."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.agents import query_understanding as qu
from app.config import settings
from app.historical import runtime
from app.main import app
from app.services import historical_service, llm_client
from tests.test_historical_integration import csv_path, seeded  # noqa: F401  (fixtures: synthetic storms in 2098/2099)

client = TestClient(app)
THIS = date.today().year
FLOOD_2010 = "how hurricane flood impacts in 2010 ?"


def parse(q):
    return qu.understand_query(q).parsed


# ------------------------------------------------------------------ rule parser: years and topics
@pytest.mark.parametrize("q,years", [
    ("how hurricane flood impacts in 2010 ?", (2010, 2010)),
    ("What happened in the Gulf between 2005 and 2008?", (2005, 2008)),
    ("hurricanes 2017-2019 in the Gulf", (2017, 2019)),
    ("hurricanes from 2012 to 2014", (2012, 2014)),
    ("Gulf hurricanes since 2015", (2015, THIS)),
    ("Gulf hurricanes before 2010", (None, 2009)),
    ("What if a hurricane hits in 2035?", (None, None)),          # future year = scenario, not history
    ("How would a Category 4 hurricane affect my holdings?", (None, None)),
])
def test_years_are_extracted(q, years):
    p = parse(q)
    assert (p.year_from, p.year_to) == years


def test_the_2010_flood_question_is_a_historical_lookup_only():
    p = parse(FLOOD_2010)
    assert p.intent == "historical_search" and p.event_type == "hurricane" and p.uses_portfolio is False
    assert p.analysis_steps == ["historical"]                      # no weather / news / market / portfolio agents
    assert p.topics == ["flooding"] and (p.year_from, p.year_to) == (2010, 2010)


def test_topics_vocabulary():
    assert parse("hurricane damage and deaths in 2005").topics == ["damage", "casualties"]
    assert parse("how did hurricane Katrina storm surge and rainfall in 2005 matter").topics == ["rainfall", "storm surge"]


def test_current_year_questions_are_not_treated_as_history():
    p = parse(f"what are hurricanes doing in {THIS}?")
    assert (p.year_from, p.year_to) == (THIS, THIS) and "weather" in p.analysis_steps       # live agents still apply


def test_past_period_with_my_portfolio_keeps_the_portfolio_pipeline():
    p = parse("How would my holdings have fared in the 2005 hurricane season?")
    assert p.uses_portfolio and p.intent == "event_impact" and (p.year_from, p.year_to) == (2005, 2005)
    assert p.analysis_steps == ["historical", "exposure", "fusion"]      # that period's record vs the portfolio; no live feeds


# ------------------------------------------------------------------ portfolio steps only when the question is about the portfolio
def test_event_questions_without_my_holdings_skip_portfolio_maths():
    p = parse("How would a Category 4 hurricane in the Gulf affect oil prices?")
    assert p.intent == "event_impact" and p.analysis_steps == ["weather", "news", "market", "historical"]
    mine = parse("How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?")
    assert mine.uses_portfolio and "hedging" in mine.analysis_steps and "fusion" in mine.analysis_steps and "drivers" not in mine.analysis_steps


# ------------------------------------------------------------------ LLM path goes through the same gate
def test_llm_plan_is_overridden_for_past_periods(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: {
        "intent": "event_impact", "event_type": "hurricane", "year_from": 2010, "topics": ["Flooding", "nonsense"],
        "uses_portfolio": False, "analysis_steps": ["weather", "news", "market", "historical", "risk"], "confidence": 0.9})
    p = parse(FLOOD_2010)
    assert p.parser == "llm" and p.intent == "historical_search" and p.analysis_steps == ["historical"]
    assert (p.year_from, p.year_to) == (2010, 2010) and p.topics == ["flooding"]            # single year mirrored; junk topic dropped


def test_llm_year_values_are_validated(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: {
        "intent": "historical_search", "event_type": "hurricane", "year_from": 2012, "year_to": 2008, "uses_portfolio": False,
        "analysis_steps": [], "confidence": 1})
    p = parse("storms between 2008 and 2012")
    assert (p.year_from, p.year_to) == (2008, 2012)                                         # reversed range is swapped
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: {
        "intent": "historical_search", "event_type": "hurricane", "year_from": "abc", "year_to": 3000, "analysis_steps": [], "confidence": 1})
    p = parse("storms")
    assert (p.year_from, p.year_to) == (None, None)


# ------------------------------------------------------------------ the historical search honours the period
def test_search_filters_by_year_and_orders_by_strength(seeded):                       # noqa: F811
    r = historical_service.search(event_type="hurricane", year_from=2099, year_to=2099, topics=["flooding"])
    assert r.status == "ok" and {m.storm.year for m in r.matches} == {2099}
    assert [m.storm.name for m in r.matches] == ["TESTGULF", "TESTATL"]               # Cat 4 before Cat 1
    assert r.query["applied_filters"]["year_from"] == 2099 and r.query["year_to"] == 2099
    assert any("no flooding information" in n for n in r.notices)
    none = historical_service.search(event_type="hurricane", year_from=2050, year_to=2050)
    assert none.status == "no_results" and none.matches == []


def test_search_warns_when_the_period_predates_the_stored_data(seeded):               # noqa: F811
    r = historical_service.search(event_type="hurricane", year_from=1970, year_to=1975)
    assert r.matches == [] and any("starts in 1980" in n for n in r.notices)


def test_pipeline_runs_only_the_historical_step_for_the_2010_question(seeded):        # noqa: F811
    body = client.post("/api/query", json={"query": FLOOD_2010}).json()
    assert [(s["step"], s["status"]) for s in body["steps"]] == [("historical", "completed")]
    assert body["weather"] is None and body["news"] is None and body["market"] is None
    assert body["exposure"] is None and body["risk"] is None and body["fusion"] is None and body["hedging"] is None
    assert body["parsed"]["intent"] == "historical_search" and body["parsed"]["year_from"] == 2010


# ------------------------------------------------------------------ news: idioms are not storm coverage
def test_news_matching_no_longer_treats_bare_storm_as_a_hurricane_match():
    from app.agents.news_agent import _EVENT_TERMS
    strong, weak = _EVENT_TERMS["hurricane"]
    assert "storm" not in weak and "storm" not in strong and "hurricane" in strong
