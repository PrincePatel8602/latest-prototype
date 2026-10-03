"""Historical retrieval service used by the Historical Agent.

PostgreSQL (NOAA IBTrACS) is the source of truth; Pinecone only adds semantic candidates, which
are re-verified against the structured filters and hydrated from PostgreSQL. No LLM, no market
data, no financial inference lives here.
"""
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.historical import repository as repo, runtime, settings
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.historical.filters import StormFilter
from app.historical.search import SearchRequest, hybrid_search
from app.schemas.common import DataMeta
from app.schemas.historical import HistoricalIntelligence, HistoricalMatch, HistoricalStorm, MarketResponse, PhysicalImpact
from app.services.common import now_utc

log = logging.getLogger("aegis.historical.service")

SUPPORTED_EVENT_TYPES = {"hurricane", "tropical_storm", "none"}


MARKET_NOTE = ("Market response = 5-day cumulative abnormal return (days 0 to +5 from first Gulf entry) against a SPY "
               "market model. Descriptive statistics from stored historical prices, not a prediction or a causal estimate.")


def _market_responses(session, storm_ids: list[str]) -> dict[str, list[dict]]:
    """Stored event-study rows for the matched storms; {} if the analytics table is absent or empty."""
    try:
        from app.analytics.runner import storm_results
        return storm_results(session, storm_ids)
    except SQLAlchemyError:
        session.rollback()
        return {}


def _physical_impacts(session, storm_ids: list[str]) -> dict[str, dict]:
    """BSEE per-storm shut-in aggregates for the matched storms; {} if the table is absent or empty."""
    try:
        from sqlalchemy import select
        from app.historical.physical.models import BseeStormShutin
        rows = session.scalars(select(BseeStormShutin).where(BseeStormShutin.storm_id.in_(storm_ids)))
        return {r.storm_id: {
            "max_oil_shut_in_pct": r.max_oil_shut_in_pct, "max_gas_shut_in_pct": r.max_gas_shut_in_pct,
            "max_platforms_evacuated": r.max_platforms_evacuated,
            "peak_oil_date": r.peak_oil_date.isoformat() if r.peak_oil_date else None,
            "n_reports_used": r.n_reports_used, "n_reports_listed": r.n_reports_listed,
            "source_urls": (r.source_urls or [])[:3], "note": r.note} for r in rows if r.n_reports_used}
    except SQLAlchemyError:
        session.rollback()
        return {}


def _empty(query: dict, status: str, notice: str) -> HistoricalIntelligence:
    """No data was served: labelled "demo" (the only non-live label) with an explicit notice."""
    return HistoricalIntelligence(
        meta=DataMeta(source="demo", notice=notice, as_of=now_utc()), status=status, query=query,  # type: ignore[arg-type]
        notices=[notice], summary=notice)


def filter_from_query(event_type: str, region: str | None, category: int | None) -> tuple[StormFilter, int | None]:
    """Turn the parsed question into deterministic filters. Returns (filter, category_target).

    The category is a target used only to ORDER structured results (closest peak first); it is
    not turned into a hard filter because "similar to a Category 4" is not "exactly Category 4".
    """
    f = StormFilter()
    if event_type in ("hurricane", "tropical_storm"):
        f.event_type = event_type
    r = (region or "").lower()
    if "gulf" in r:
        f.gulf_only, f.basin, f.category_scope = True, "NA", "gulf"
    elif "atlantic" in r or "caribbean" in r:
        f.basin = "NA"
    return f, category


UNCOVERED_TOPICS = {"flooding", "damage", "casualties", "rainfall", "storm surge", "costs"}
DATA_STARTS = 1980


def search(*, event_type: str = "none", region: str | None = None, category: int | None = None,
           sectors: list[str] | None = None, query: str = "", limit: int = 6,
           year_from: int | None = None, year_to: int | None = None, topics: list[str] | None = None) -> HistoricalIntelligence:
    # `sectors` is accepted for API compatibility; hazard records carry no sector information.
    echo = {"event_type": event_type, "region": region, "category": category, "text": query.strip(),
            "year_from": year_from, "year_to": year_to}
    if event_type not in SUPPORTED_EVENT_TYPES:
        return _empty(echo, "unsupported_event",
                      f"The historical dataset (NOAA IBTrACS) covers tropical cyclones only, not {event_type!r}.")
    if not runtime.database_enabled():
        return _empty(echo, "unavailable", "Historical database is not configured (DATABASE_URL); no historical data shown.")

    f, target = filter_from_query(event_type, region, category)
    f.year_from, f.year_to = year_from, year_to
    if year_from or year_to:
        limit = max(limit, 25)               # "everything from that period", strongest first, not a top-6 analogue list
    text = " ".join(x for x in (event_type if event_type != "none" else "", region or "",
                                f"category {category}" if category else "") if x)
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured as e:
        return _empty(echo, "unavailable", str(e))
    try:
        total = repo.count_storms(session)
        if total == 0:
            return _empty(echo, "no_results",
                          "Historical database is empty. Run scripts/import_ibtracs.py to load NOAA IBTrACS.")
        res = hybrid_search(session, SearchRequest(filter=f, query_text=text or None, top_k=limit,
                                                   use_semantic=True, category_target=target), runtime.vector_store())
        responses = _market_responses(session, [h.storm["storm_id"] for h in res.hits])
        physical = _physical_impacts(session, [h.storm["storm_id"] for h in res.hits])
        run = repo.latest_run(session)
        dataset = {"source": settings.SOURCE_NAME, "dataset_version": settings.SOURCE_VERSION,
                   "storms_in_database": total, "source_url": settings.SOURCE_LANDING_URL,
                   "last_ingestion": run.started_at.isoformat() if run else None,
                   "last_ingestion_subset": run.subset if run else None}
    except SQLAlchemyError as e:
        log.error("historical database error: %s", type(e).__name__)
        return _empty(echo, "unavailable", "Historical database is unreachable; no historical data shown.")
    finally:
        session.close()

    notices = list(res.notices)
    missing = [t for t in (topics or []) if t in UNCOVERED_TOPICS]
    if missing:
        notices.append(f"The stored historical data (NOAA IBTrACS storm tracks and intensity, market prices, BSEE shut-ins) has no "
                       f"{', '.join(missing)} information; only storm intensity, track and market response are shown.")
    if (year_from and year_from < DATA_STARTS) or (year_to and year_to < DATA_STARTS):
        notices.append(f"Stored storm data starts in {DATA_STARTS}; earlier years are not available.")
    matches = [HistoricalMatch(storm=HistoricalStorm.model_validate(h.storm),
                               market_response=[MarketResponse.model_validate(m) for m in responses.get(h.storm["storm_id"], [])],
                               physical_impact=(PhysicalImpact.model_validate(physical[h.storm["storm_id"]])
                                                if h.storm["storm_id"] in physical else None),
                               retrieval_method=h.retrieval_method,
                               similarity_score=h.similarity_score, match_reasons=h.match_reasons) for h in res.hits]
    if year_from or year_to:      # a period listing is ordered by storm strength, not by an (irrelevant) similarity score
        matches.sort(key=lambda m: (-(m.storm.max_category_normalized if m.storm.max_category_normalized is not None else -9),
                                    -(m.storm.max_wind_kt or 0), m.storm.year))
    applied = {k: v for k, v in f.__dict__.items() if v not in (None, False) and k != "category_scope"}
    if matches:
        summary = (f"Retrieved {len(matches)} historical tropical-cyclone record(s) from {settings.SOURCE_NAME} "
                   f"{settings.SOURCE_VERSION} via {res.retrieval_method} retrieval (filters: {applied or 'none'}). "
                   "Records describe the physical event only; no market impact is inferred.")
    else:
        summary = "No stored historical event matched the structured filters."
    return HistoricalIntelligence(
        meta=DataMeta(source="live", notice=f"{settings.SOURCE_NAME} {settings.SOURCE_VERSION} from PostgreSQL",
                      as_of=now_utc()),
        status="ok" if matches else "no_results", query={**echo, "applied_filters": applied}, matches=matches,
        retrieval_method=res.retrieval_method, semantic_status=res.semantic_status, dataset=dataset,
        market_response_note=MARKET_NOTE if any(m.market_response for m in matches) else None,
        notices=notices, summary=summary)
