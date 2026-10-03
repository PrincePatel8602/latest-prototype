from fastapi import APIRouter

from app.config import settings
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Used by the frontend (and later Docker) to check the backend is alive."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        demo_mode=settings.demo_mode,
        integrations={
            "llm": bool(settings.llm_api_key),
            "market": bool(settings.market_api_key),
            "weather": True,  # NOAA NHC feed needs no key
            "news": bool(settings.news_api_key),
            "pinecone": bool(settings.pinecone_api_key),
            "database": bool(settings.database_url),
        },
    )
