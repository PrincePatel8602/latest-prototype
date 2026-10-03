from fastapi import APIRouter

from app.schemas.portfolio import PortfolioIn, PortfolioResponse
from app.services import portfolio_service

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioResponse)
def read_portfolio() -> PortfolioResponse:
    return portfolio_service.get_portfolio()


@router.post("/portfolio", response_model=PortfolioResponse)
def save_portfolio(body: PortfolioIn) -> PortfolioResponse:
    """Replace the portfolio. FastAPI returns 422 automatically if invalid."""
    return portfolio_service.set_portfolio(body)
