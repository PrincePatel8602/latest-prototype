import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import dashboard, health, historical, insights, market, news, portfolio, query, weather
from app.config import settings

app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.app_version,
    description="Multi-agent financial intelligence backend.",
)

# CORS: browsers block cross-origin calls unless the server explicitly allows
# them. We only allow the frontend origin(s) listed in .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(market.router)
app.include_router(weather.router)
app.include_router(news.router)
app.include_router(query.router)
app.include_router(historical.router)
app.include_router(dashboard.router)
app.include_router(insights.router)


def _warm_caches() -> None:
    """Fill the 5-minute caches behind the dashboard/insight endpoints so the first visitor does not wait on the database."""
    try:
        dashboard.summary()
        insights.risk_drivers()
    except Exception as e:  # noqa: BLE001  (optional optimisation: never affects startup)
        logging.getLogger("aegis.warmup").info("cache warm-up skipped: %s", type(e).__name__)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_warm_caches, daemon=True, name="cache-warmup").start()
