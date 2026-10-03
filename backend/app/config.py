"""Central configuration.

All secrets and settings are read from environment variables (.env file).
Nothing sensitive is ever hard-coded. pydantic-settings validates the values
at startup, so a typo in .env fails loudly instead of silently.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The .env file lives at the project root (one level above backend/).
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), extra="ignore"
    )

    app_name: str = "FinSight AI"
    app_version: str = "0.1.0"

    # DEMO_MODE=true  -> NO external calls at all; everything uses built-in demo
    #                    data (deterministic, safe for presentations).
    # DEMO_MODE=false -> try live APIs first; fall back to demo data per source
    #                    (with a visible notice) if a key is missing or the API fails.
    demo_mode: bool = True

    # Which browser origins may call this API (comma-separated).
    cors_origins: str = "http://localhost:3000"

    # Optional keys. Empty string = "not configured" -> app falls back to demo data.
    llm_api_key: str = ""
    # Which LLM provider/model parses the user's question (Phase 5).
    # llm_provider: "anthropic" or "openai". Empty llm_model = sensible default.
    llm_provider: str = "anthropic"
    llm_model: str = ""
    market_api_key: str = ""   # Finnhub (https://finnhub.io)
    news_api_key: str = ""     # NewsAPI.org (https://newsapi.org)
    # Weather needs no key: it uses the free public NOAA National Hurricane Center feed.
    pinecone_api_key: str = ""
    database_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
