import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.query_understanding import understand_query
from app.graph.builder import run_pipeline, stream_pipeline
from app.schemas.pipeline import QueryPipelineResponse
from app.schemas.query import QueryIn, QueryParseResponse

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query/parse", response_model=QueryParseResponse)
def parse_query(body: QueryIn) -> QueryParseResponse:
    """Phase 5: understand the question only (no analysis)."""
    return understand_query(body.query)


@router.post("/query", response_model=QueryPipelineResponse)
def run_query(body: QueryIn) -> QueryPipelineResponse:
    """Full pipeline (LangGraph): understand the question, then run ONLY the agents it needs.

    Implemented phases 9-10: historical retrieval, portfolio exposure, scenario analysis and quantitative risk.
    Later requested steps such as hedging remain explicitly marked not implemented.
    """
    return run_pipeline(body.query)


@router.post("/query/stream")
def run_query_stream(body: QueryIn) -> StreamingResponse:
    """Same analysis as POST /api/query, streamed as newline-delimited JSON: plan, step_start, step_done (with measured
    duration), then the full result. The UI uses it to show what is really happening while the agents run."""
    def lines():
        for event in stream_pipeline(body.query):
            yield json.dumps(event, separators=(",", ":")) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
