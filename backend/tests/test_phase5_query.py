"""Phase 5: query understanding. The LLM is always faked - no network, no cost."""
import pytest
from fastapi.testclient import TestClient

from app.agents import query_understanding as qu
from app.config import settings
from app.main import app
from app.services import llm_client
from app.services.providers.base import ProviderError

client = TestClient(app)
ACCEPTANCE = "How will a Category 4 hurricane in the Gulf of Mexico affect my current energy holdings?"


def parse(q: str) -> dict:
    r = client.post("/api/query/parse", json={"query": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_acceptance_query_rules_parser():
    body = parse(ACCEPTANCE)
    p = body["parsed"]
    assert p["parser"] == "rules" and "Demo mode is ON" in body["notice"]
    assert p["intent"] == "event_impact" and p["event_type"] == "hurricane"
    assert p["event_category"] == 4 and p["region"] == "Gulf of Mexico"
    assert p["sectors"] == ["Energy"] and p["uses_portfolio"] is True
    assert p["analysis_steps"] == ["weather", "news", "market", "historical", "exposure", "scenario", "risk", "fusion", "hedging"]
    assert p["supported"] is True


@pytest.mark.parametrize("q,intent", [
    ("What are the biggest risks to my portfolio today?", "portfolio_risk"),
    ("Find historical events similar to this one.", "historical_search"),
    ("Which assets are most exposed?", "exposure"),
    ("Explain why my portfolio risk increased.", "explain_risk"),
    ("Show possible hedging strategies.", "hedging"),
    ("What is the capital of France?", "other"),
])
def test_all_suggested_queries(q, intent):
    assert parse(q)["parsed"]["intent"] == intent


def test_time_horizon_and_number_words():
    p = parse("Impact of a category four hurricane on XOM over the next 3 days")["parsed"]
    assert p["event_category"] == 4 and p["time_horizon_days"] == 3
    assert "XOM" in p["assets"]


def test_unsupported_event_is_flagged():
    p = parse("How would an earthquake in Japan hurt my tech holdings?")["parsed"]
    assert p["event_type"] == "earthquake" and p["supported"] is False and p["warnings"]


@pytest.mark.parametrize("bad", ["", "ab", "x" * 501])
def test_rejects_bad_input(bad):
    assert client.post("/api/query/parse", json={"query": bad}).status_code == 422


def test_control_characters_are_stripped():
    body = parse("How will a hurricane\x00\x07 hit\n\n my   energy holdings\u200b?")
    assert body["query"] == "How will a hurricane hit my energy holdings?"


def test_coerce_rejects_garbage_from_llm():
    p = qu._coerce({"intent": "DROP TABLE", "event_type": "alien invasion", "event_category": 99,
                    "sectors": ["energy", "Crypto"], "assets": ["XOM", "XOM", "<script>"],
                    "confidence": "very", "analysis_steps": ["weather", "hack"], "uses_portfolio": "yes"},
                   parser="llm", model="m")
    assert p.intent == "other" and p.event_type == "other" and p.supported is False
    assert p.event_category is None and p.sectors == ["Energy"] and p.confidence == 0.5
    assert p.analysis_steps == ["weather"] and p.uses_portfolio is False  # "yes" string is not True
    assert p.assets == ["XOM"]  # duplicate + "<script>" dropped


def _llm_on(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "llm_api_key", "k")


def test_llm_path_used_and_sends_only_the_question(monkeypatch):
    _llm_on(monkeypatch)
    sent = {}

    def fake(system, user):
        sent["user"] = user
        return {"intent": "event_impact", "event_type": "hurricane", "event_category": 4,
                "region": "Gulf of Mexico", "sectors": ["Energy"], "uses_portfolio": True, "confidence": 0.9}
    monkeypatch.setattr(llm_client, "complete_json", fake)
    body = parse(ACCEPTANCE)
    assert body["parsed"]["parser"] == "llm" and body["notice"] is None
    assert body["parsed"]["analysis_steps"][0] == "weather"        # defaults filled in
    # Privacy: no holdings / weights / portfolio values in the LLM prompt.
    for secret in ("ExxonMobil", "1240000", "weight", "Demo Energy-Heavy"):
        assert secret not in sent["user"]


def test_llm_failure_falls_back_to_rules(monkeypatch):
    _llm_on(monkeypatch)
    monkeypatch.setattr(llm_client, "complete_json", lambda s, u: (_ for _ in ()).throw(ProviderError("timeout")))
    body = parse(ACCEPTANCE)
    assert body["parsed"]["parser"] == "rules" and "LLM unavailable" in body["notice"]


def test_extract_json_handles_fences_and_chatter():
    assert llm_client.extract_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("no json here", "{broken", "[1,2]"):
        with pytest.raises(ProviderError):
            llm_client.extract_json_object(bad)
