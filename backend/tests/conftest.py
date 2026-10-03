"""Shared test setup: every test starts in demo mode with a clean cache."""
import pytest

from app.config import settings
from app.services import common, llm_client, portfolio_service


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)   # tests never reach the real Pinecone
    monkeypatch.delenv("DATABASE_URL", raising=False)   # tests never touch a real historical database
    monkeypatch.setattr(settings, "demo_mode", True)
    for key in ("market_api_key", "news_api_key", "llm_api_key"):
        monkeypatch.setattr(settings, key, "")
    common.clear_cache()
    llm_client.reset_state()
    portfolio_service.reset_portfolio()
    yield
    common.clear_cache()
    portfolio_service.reset_portfolio()
