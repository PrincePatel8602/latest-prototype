from fastapi import APIRouter

from app.agents.market_agent import run_market_agent
from app.agents.query_understanding import understand_query
from app.schemas.market import MarketResponse
from app.schemas.pipeline import AnalyzeIn, MarketAgentResponse
from app.services import market_service

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/market", response_model=MarketResponse)
def read_market() -> MarketResponse:
    """Raw quotes for the user's holdings + crude proxy (dashboard panel)."""
    return market_service.get_market()


@router.post("/market/analyze", response_model=MarketAgentResponse)
def analyze_market(body: AnalyzeIn) -> MarketAgentResponse:
    """Phase 7 Market Agent: which assets are relevant to a question, with their quotes."""
    if body.parsed is not None:
        return MarketAgentResponse(query=None, parsed=body.parsed, market=run_market_agent(body.parsed))
    assert body.query is not None
    r = understand_query(body.query)
    return MarketAgentResponse(query=r.query, parsed=r.parsed, parse_notice=r.notice,
                               market=run_market_agent(r.parsed))
