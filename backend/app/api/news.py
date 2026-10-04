from fastapi import APIRouter

from app.agents.news_agent import run_news_agent
from app.agents.query_understanding import understand_query
from app.schemas.news import NewsResponse
from app.schemas.pipeline import AnalyzeIn, NewsAgentResponse
from app.services import news_service

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news", response_model=NewsResponse)
def read_news() -> NewsResponse:
    """Raw default energy headlines (dashboard panel)."""
    return news_service.get_news()


@router.post("/news/analyze", response_model=NewsAgentResponse)
def analyze_news(body: AnalyzeIn) -> NewsAgentResponse:
    """Phase 7 News Agent: relevant, labeled news for a question (`query`) or a `parsed` query."""
    if body.parsed is not None:
        return NewsAgentResponse(query=None, parsed=body.parsed, news=run_news_agent(body.parsed))
    assert body.query is not None  # guaranteed by AnalyzeIn validation
    r = understand_query(body.query)
    return NewsAgentResponse(query=r.query, parsed=r.parsed, parse_notice=r.notice,
                             news=run_news_agent(r.parsed))
