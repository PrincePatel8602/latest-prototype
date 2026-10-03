from app.schemas.portfolio import PortfolioResponse
from app.schemas.query import ParsedQuery
from app.schemas.risk import ExposureAnalysis, ScenarioAnalysis, RiskAnalysis
from app.quant.risk_engine import exposure, scenario_hurricane, risk
from app.schemas.drivers import RiskDrivers
from app.schemas.fusion import FusionAssessment
from app.schemas.hedging import HedgingAnalysis
from app.services import portfolio_service


def _portfolio() -> PortfolioResponse:
    return portfolio_service.get_portfolio()


def run_exposure_agent(parsed: ParsedQuery) -> ExposureAnalysis:
    return exposure(_portfolio())


def run_scenario_agent(parsed: ParsedQuery) -> ScenarioAnalysis:
    return scenario_hurricane(_portfolio()) if parsed.event_type in ("hurricane", "tropical_storm") else scenario_hurricane(_portfolio())


def run_risk_agent(parsed: ParsedQuery, scenario: ScenarioAnalysis | None = None) -> RiskAnalysis:
    from app.services.risk_data import real_returns
    pf = _portfolio()
    # real stored returns when every non-OTHER holding has price history; otherwise risk() falls back to its labelled assumptions
    return risk(pf, scenario, real_returns(pf))


def run_fusion_agent(parsed: ParsedQuery, *, weather=None, news=None, market=None, scenario=None) -> FusionAssessment:
    """Evidence fusion (Phase 13): stored historical evidence applied to the current portfolio. No LLM involved."""
    from app.services.fusion_service import run_fusion
    return run_fusion(parsed, weather=weather, news=news, market=market, scenario=scenario)


def run_drivers_agent(parsed: ParsedQuery, *, weather=None, news=None, market=None) -> RiskDrivers:
    """Risk drivers (Phase 13): did risk change recently, and which holdings drive it? Python only, no LLM."""
    from app.services.drivers_service import run_drivers
    return run_drivers(parsed, weather=weather, news=news, market=market)


def run_hedging_agent(parsed: ParsedQuery, *, risk=None) -> HedgingAnalysis:
    """Hedging (Phase 13): which instruments historically reduced this portfolio's risk, and how stable was that? No LLM, no advice."""
    from app.services.hedging_service import run_hedging
    return run_hedging(parsed, risk=risk)
