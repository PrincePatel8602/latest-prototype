"""Dashboard tiles: two small, cached summaries computed from stored history (no LLM, no live-API calls)."""
from fastapi import APIRouter

from app.schemas.query import ParsedQuery
from app.services.drivers_service import run_drivers
from app.services.fusion_service import run_fusion
from app.utils.cache import TTLCache

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
_cache = TTLCache()
TTL_S = 300
# The fixed reference event for the "hurricane impact" tile: a Category 4 hurricane in the Gulf of Mexico.
_REFERENCE = ParsedQuery(intent="event_impact", event_type="hurricane", event_category=4, region="Gulf of Mexico",
                         confidence=1.0, parser="rules")
_GENERIC = ParsedQuery(intent="portfolio_risk", confidence=1.0, parser="rules")


def build_summary() -> dict:
    d = run_drivers(_GENERIC)
    risk = {"status": d.status, "note": d.conclusion if d.status != "ok" else None}
    if d.status == "ok" and d.risk_change:
        rc = d.risk_change
        risk.update(classification=rc.classification, recent_vol_pct=rc.recent_vol_pct, year_vol_pct=rc.year_vol_pct,
                    history_percentile=rc.history_percentile, window_days=rc.window_days, prices_as_of=d.prices_as_of,
                    top_risk_symbol=d.holdings[0].symbol if d.holdings else None, covered_weight_pct=d.covered_weight_pct)
    f = run_fusion(_REFERENCE)
    impact = {"status": f.status, "reference_event": "Category 4 Gulf hurricane", "note": f.conclusion if f.status != "ok" else None}
    if f.status == "ok" and f.portfolio:
        a = f.portfolio.all_analogs
        impact.update(n_storms=a.n, median_pct=a.median, p10_pct=a.p10, p90_pct=a.p90, grade=a.grade, median_usd=f.portfolio.median_usd,
                      p10_usd=f.portfolio.p10_usd, p90_usd=f.portfolio.p90_usd, covered_weight_pct=f.portfolio.covered_weight_pct,
                      storms=[p.model_dump() for p in f.portfolio.per_storm])
    return {"risk": risk, "hurricane_impact": impact}


@router.get("/summary")
def summary() -> dict:
    """Portfolio-risk and reference-hurricane tiles. Cached 5 minutes; 'unavailable' statuses are reported, never faked."""
    hit = _cache.get("summary")
    if hit is not None:
        return hit
    out = build_summary()
    if out["risk"]["status"] == "ok" and out["hurricane_impact"]["status"] == "ok":    # only cache complete results
        _cache.set("summary", out, TTL_S)
    return out
