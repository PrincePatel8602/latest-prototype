"""Historical data REST API (PostgreSQL = source of truth, Pinecone = semantic helper).

Register once in app/main.py:
    from app.api import historical as historical_api
    app.include_router(historical_api.router)
"""
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.historical import repository as repo, runtime, settings
from app.historical.database import DatabaseNotConfigured, get_sessionmaker
from app.historical.repository import StormFilter
from app.historical.search import SearchRequest, hybrid_search
from app.schemas.historical import HistoricalSearchHit, HistoricalSearchRequest, HistoricalSearchResponse

router = APIRouter(prefix="/api/historical", tags=["historical"])


def get_session() -> Iterator[Session]:
    try:
        session = get_sessionmaker()()
    except DatabaseNotConfigured as e:
        raise HTTPException(status_code=503, detail="Historical database is not configured (DATABASE_URL).") from e
    try:
        yield session
    finally:
        session.close()


def _filter_from(**kw) -> StormFilter:
    return StormFilter(**{k: v for k, v in kw.items() if v is not None})


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    run = repo.latest_run(session)
    store = runtime.vector_store()
    return {
        "storms": repo.count_storms(session),
        "pinecone": {"configured": store is not None, "namespace": store.namespace if store else None,
                     "records": store.count() if store else None},
        "last_ingestion": None if run is None else {
            "started_at": run.started_at.isoformat(), "status": run.status, "mode": run.mode,
            "source": run.source, "dataset_version": run.source_version, "subset": run.subset},
        "source_url": settings.SOURCE_LANDING_URL,
    }


@router.get("/storms")
def list_storms(name: str | None = None, year: int | None = None, year_from: int | None = None,
                year_to: int | None = None, basin: str | None = None, event_type: str | None = None,
                min_category: int | None = Query(None, ge=-1, le=5), max_category: int | None = Query(None, ge=-1, le=5),
                gulf_only: bool = False, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
                session: Session = Depends(get_session)) -> dict:
    f = _filter_from(name=name, year=year, year_from=year_from, year_to=year_to, basin=basin, event_type=event_type,
                     min_category=min_category, max_category=max_category, gulf_only=gulf_only or None)
    rows = repo.query_storms(session, f, limit=limit, offset=offset)
    return {"total": repo.count_storms(session, f), "limit": limit, "offset": offset,
            "storms": [repo.storm_to_dict(r) for r in rows]}


@router.get("/storm/{storm_id}")
def get_storm(storm_id: str, include_track: bool = False, session: Session = Depends(get_session)) -> dict:
    row = repo.get_storm(session, storm_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Storm {storm_id!r} not found")
    out = repo.storm_to_dict(row)
    if include_track:
        out["track"] = [repo.track_point_to_dict(p) for p in repo.get_track(session, storm_id)]
    return out


@router.get("/stats")
def stats(basin: str | None = None, gulf_only: bool = False, year_from: int | None = None, year_to: int | None = None,
          session: Session = Depends(get_session)) -> dict:
    """Deterministic descriptive statistics (counts / durations) - groundwork for later analytics."""
    f = _filter_from(basin=basin, gulf_only=gulf_only or None, year_from=year_from, year_to=year_to)
    return {"filters": {k: v for k, v in f.__dict__.items() if v is not None and v is not False},
            "peak_category_distribution": repo.category_distribution(session, f),
            "duration": repo.duration_stats(session, f)}


@router.post("/search", response_model=HistoricalSearchResponse)
def search(body: HistoricalSearchRequest, session: Session = Depends(get_session)) -> HistoricalSearchResponse:
    f = StormFilter(name=body.name, basin=body.basin, event_type=body.event_type, year_from=body.year_from,
                    year_to=body.year_to, min_category=body.min_category, max_category=body.max_category,
                    category_scope=body.category_scope, gulf_only=body.gulf_of_mexico, min_wind_kt=body.min_wind_kt)
    res = hybrid_search(session, SearchRequest(filter=f, query_text=body.query, top_k=body.top_k,
                                               use_semantic=body.use_semantic, category_target=body.category_target),
                        runtime.vector_store())
    return HistoricalSearchResponse(
        hits=[HistoricalSearchHit(storm=h.storm, retrieval_method=h.retrieval_method,
                                  similarity_score=h.similarity_score, match_reasons=h.match_reasons)
              for h in res.hits],
        retrieval_method=res.retrieval_method, semantic_status=res.semantic_status, notices=res.notices,
        structured_candidates=res.structured_candidates, semantic_candidates=res.semantic_candidates,
        applied_filters={k: v for k, v in f.__dict__.items() if v is not None and v is not False})


@router.get("/event-study/{storm_id}")
def storm_event_study(storm_id: str, all_series: bool = False, session: Session = Depends(get_session)) -> dict:
    """Stored event-study statistics for one storm (key energy series by default, every series with all_series=true)."""
    from app.analytics.runner import KEY_SERIES, storm_results
    if repo.get_storm(session, storm_id) is None:
        raise HTTPException(status_code=404, detail=f"Storm {storm_id!r} not found")
    rows = storm_results(session, [storm_id], None if all_series else KEY_SERIES).get(storm_id, [])
    return {"storm_id": storm_id, "results": rows,
            "note": "Descriptive abnormal returns vs a SPY market model; not a prediction or causal estimate.",
            "computed": bool(rows)}


@router.get("/event-study-summary")
def event_study_summary(group: str = Query("hurricane", pattern="^(all|hurricane|major)$"),
                        window: str = Query("0,5", pattern=r"^-?\d+,-?\d+$"), exclude_overlap: bool = True,
                        session: Session = Depends(get_session)) -> dict:
    """Cross-storm distribution of CARs per series, with sample sizes. group: all Gulf storms | hurricane (Cat>=1 in Gulf) | major (Cat>=3)."""
    from sqlalchemy import select
    from app.analytics.runner import aggregate
    from app.historical.models import HistoricalStorm as S
    ids = None
    if group != "all":
        floor = 1 if group == "hurricane" else 3
        ids = set(session.scalars(select(S.storm_id).where(S.max_category_in_gulf >= floor)))
    return {"group": group, "window": window, "exclude_overlap": exclude_overlap,
            "series": aggregate(session, storm_ids=ids, window=window, exclude_overlap=exclude_overlap),
            "note": ("Small samples: with overlap excluded few independent storms remain; read n and t_stat before "
                     "drawing any conclusion. Descriptive, not causal.")}


@router.get("/shut-ins/{storm_id}")
def storm_shut_ins(storm_id: str, session: Session = Depends(get_session)) -> dict:
    """BSEE Gulf production shut-in statistics for one storm: the per-storm maximum plus every verified daily report."""
    from sqlalchemy import select
    from app.historical.physical.models import BseeReport, BseeStormShutin
    if repo.get_storm(session, storm_id) is None:
        raise HTTPException(status_code=404, detail=f"Storm {storm_id!r} not found")
    agg = session.scalar(select(BseeStormShutin).where(BseeStormShutin.storm_id == storm_id))
    if agg is None:
        return {"storm_id": storm_id, "available": False, "reports": [],
                "note": "No BSEE shut-in statistics are stored for this storm (BSEE coverage is 2011 onward and Gulf storms only)."}
    reports = session.scalars(select(BseeReport).where(BseeReport.index_year == agg.year, BseeReport.storm_label == agg.storm_label,
                                                       BseeReport.accepted.is_(True)).order_by(BseeReport.report_date))
    return {"storm_id": storm_id, "available": True,
            "summary": {"storm_label": agg.storm_label, "max_oil_shut_in_pct": agg.max_oil_shut_in_pct,
                        "max_gas_shut_in_pct": agg.max_gas_shut_in_pct, "max_platforms_evacuated": agg.max_platforms_evacuated,
                        "peak_oil_date": agg.peak_oil_date.isoformat() if agg.peak_oil_date else None,
                        "n_reports_used": agg.n_reports_used, "n_reports_listed": agg.n_reports_listed, "note": agg.note},
            "reports": [{"date": r.report_date.isoformat() if r.report_date else None, "oil_shut_in_pct": r.oil_shut_in_pct,
                         "gas_shut_in_pct": r.gas_shut_in_pct, "platforms_evacuated": r.platforms_evacuated, "url": r.url,
                         "raw_sha256": r.raw_sha256} for r in reports],
            "source": "BSEE storm activity statistics (press releases)"}


@router.get("/shutin-response")
def shutin_response(window: str = Query("0,5", pattern=r"^-?\d+,-?\d+$"), exclude_overlap: bool = True,
                    session: Session = Depends(get_session)) -> dict:
    """Do storms with larger Gulf production shut-ins show different abnormal returns? Rank correlation + high/low split."""
    from app.analytics.shutin_link import shutin_vs_response
    return {"window": window, "exclude_overlap": exclude_overlap,
            "series": shutin_vs_response(session, window=window, exclude_overlap=exclude_overlap),
            "note": "Descriptive and based on very few storms; signs can change with the overlap rule. Not a causal estimate."}
