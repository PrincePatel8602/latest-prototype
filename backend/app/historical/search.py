"""Hybrid historical retrieval: deterministic structured filtering + semantic similarity.

    structured filters ──► PostgreSQL ─────────────┐
                                                   ├─► merge/dedupe ─► hydrate from PostgreSQL ─► provenance
    query text ──► Pinecone (metadata pre-filter) ─┘        (semantic candidates are re-verified
                                                             against the structured filter)

Ranking is an ORDERING RULE, not a confidence score (no invented weights):
  1. found by BOTH structured filter and semantic search (closest peak category to the target, then Pinecone score desc)
  2. structured only (closest peak category to the target, then stronger wind, then newer)
  3. semantic only (by Pinecone score desc)
`similarity_score` is the raw Pinecone score and is None for anything Pinecone did not return.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.historical import repository as repo
from app.historical.filters import StormFilter, storm_matches
from app.historical.vector_store import HistoricalVectorStore, to_pinecone_filter


@dataclass
class SearchRequest:
    filter: StormFilter = field(default_factory=StormFilter)
    query_text: str | None = None
    top_k: int = 10
    use_semantic: bool = True
    category_target: int | None = None     # only used to order structured results


@dataclass
class SearchHit:
    storm: dict
    retrieval_method: str                  # structured+semantic | structured | semantic
    similarity_score: float | None
    match_reasons: list[str]


@dataclass
class SearchResult:
    hits: list[SearchHit]
    retrieval_method: str                  # overall method actually used
    semantic_status: str                   # ok | disabled | not_configured | no_query | error: <Type>
    notices: list[str]
    structured_candidates: int = 0
    semantic_candidates: int = 0


def _strip(event_id: str) -> str:
    return event_id.split(":", 1)[1] if ":" in event_id else event_id


def _cat(storm: dict, f: StormFilter):
    return storm["max_category_in_gulf"] if f.category_scope == "gulf" else storm["max_category_normalized"]


def hybrid_search(session: Session, req: SearchRequest, vector_store: HistoricalVectorStore | None) -> SearchResult:
    f, notices = req.filter, []

    # ---- A. deterministic structured retrieval
    structured: dict[str, dict] = {}
    if f.is_active():
        for row in repo.query_storms(session, f, limit=max(req.top_k * 5, 100)):
            structured[row.storm_id] = repo.storm_to_dict(row)

    # ---- B. semantic retrieval (never silently skipped)
    semantic: dict[str, float] = {}
    status = "ok"
    if not req.use_semantic:
        status = "disabled"
    elif not req.query_text:
        status = "no_query"
    elif vector_store is None:
        status = "not_configured"
        notices.append("Semantic retrieval unavailable: Pinecone is not configured; results use structured filters only.")
    else:
        try:
            for h in vector_store.search(req.query_text, top_k=max(req.top_k * 2, 10), filter=to_pinecone_filter(f)):
                semantic[_strip(h.event_id)] = h.score
        except Exception as e:                                            # noqa: BLE001
            status = f"error: {type(e).__name__}"
            notices.append(f"Semantic retrieval failed ({type(e).__name__}); results use structured filters only.")

    # ---- C. hydrate semantic-only ids from PostgreSQL and re-verify the structured filter
    missing = [sid for sid in semantic if sid not in structured]
    rejected = 0
    hydrated = repo.get_storms_by_ids(session, missing)
    semantic_only: dict[str, dict] = {}
    for sid in missing:
        row = hydrated.get(sid)
        if row is None:
            notices.append(f"Pinecone returned {sid}, which is not in PostgreSQL; ignored (index may be stale).")
            continue
        d = repo.storm_to_dict(row)
        if storm_matches(d, f):
            semantic_only[sid] = d
        else:
            rejected += 1
    if rejected:
        notices.append(f"{rejected} semantic candidate(s) were dropped because they fail the structured filters.")
    semantic = {sid: sc for sid, sc in semantic.items() if sid in structured or sid in semantic_only}

    # ---- D. merge + order
    t = req.category_target
    both = sorted((s for s in structured if s in semantic),
                  key=lambda s: (abs((_cat(structured[s], f) or 0) - t) if t is not None else 0, -semantic[s]))
    s_only = [s for s in structured if s not in semantic]
    s_only.sort(key=lambda s: (abs((_cat(structured[s], f) or 0) - t) if t is not None else 0,
                               -(structured[s]["max_wind_kt"] or 0), -structured[s]["year"], s))
    m_only = sorted(semantic_only, key=lambda s: -semantic[s])

    hits: list[SearchHit] = []
    for sid in both + s_only + m_only:
        storm = structured.get(sid) or semantic_only[sid]
        in_s, in_m = sid in structured, sid in semantic
        method = "structured+semantic" if in_s and in_m else "structured" if in_s else "semantic"
        reasons = []
        if in_s:
            reasons.append("matches structured filters")
        if in_m:
            reasons.append("semantically similar (Pinecone)")
        if t is not None and _cat(storm, f) is not None:
            d = abs(_cat(storm, f) - t)
            reasons.append("same peak category" if d == 0 else "adjacent peak category" if d == 1 else f"peak category differs by {d}")
        hits.append(SearchHit(storm=storm, retrieval_method=method, similarity_score=semantic.get(sid),
                              match_reasons=reasons))

    if not f.is_active() and not semantic:
        # nothing to filter on and no semantic evidence: explicit, labelled fallback ordering by severity
        for row in repo.query_storms(session, f, limit=req.top_k):
            hits.append(SearchHit(repo.storm_to_dict(row), "structured_unfiltered", None, ["ordered by peak intensity"]))
        notices.append("No filters or semantic query supplied; showing the most intense stored storms.")

    hits = hits[:req.top_k]
    overall = ("structured+semantic" if structured and semantic else "structured" if structured
               else "semantic" if semantic_only else "structured_unfiltered" if hits else "none")
    return SearchResult(hits=hits, retrieval_method=overall, semantic_status=status, notices=notices,
                        structured_candidates=len(structured), semantic_candidates=len(semantic))
