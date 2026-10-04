from app.services.historical_service import search
from app.quant.risk_engine import exposure, scenario_hurricane, risk
from app.services.portfolio_service import get_portfolio


def test_historical_agent_never_fabricates_when_no_database():
    """Phase 11 replaced the bundled demo JSON with PostgreSQL-backed NOAA IBTrACS retrieval.
    Without a configured database the agent must say so and return no events (conftest unsets DATABASE_URL).
    The populated-database path is covered in test_historical_integration.py."""
    result = search(event_type="hurricane", region="Gulf of Mexico", category=4, sectors=["Energy"])
    assert result.status == "unavailable"
    assert result.matches == []


def test_scenario_uses_portfolio_weights():
    p = get_portfolio()
    result = scenario_hurricane(p)
    # 30%*5% + 20%*5% + 15%*8% = 3.7%
    assert round(result.estimated_portfolio_change_pct, 2) == 3.70
    assert round(result.estimated_portfolio_change_usd, 2) == 45880.00


def test_risk_does_not_fake_historical_var():
    p = get_portfolio()
    result = risk(p, scenario_hurricane(p))
    assert result.volatility_method == "assumption_based_weighted_volatility"
    assert result.historical_var_95_pct is None
    assert result.historical_var_method == "not_available"
