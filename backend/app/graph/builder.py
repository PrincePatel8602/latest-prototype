"""Phase 8: the LangGraph pipeline.

    understand -> router -> weather -> router -> news -> router -> market -> router -> finalize

`router` is a conditional edge that looks at ParsedQuery.analysis_steps (already stored in
`pending`) and sends control to the next implemented agent that the question needs. Agents the
question does not need are never called. To add a future agent: write a node, add it to
IMPLEMENTED and to `_AGENT_NODES` - nothing else changes.

Execution is deterministic and sequential (no parallel branches): later agents will want to read
earlier agents' output (e.g. scenario needs weather + market).
"""
import time
from functools import lru_cache
from typing import Iterator

from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.state import PipelineState
from app.schemas.pipeline import AgentRun, QueryPipelineResponse

_AGENT_NODES = {
    "weather": nodes.weather_node,
    "news": nodes.news_node,
    "market": nodes.market_node,
    "historical": nodes.historical_node,
    "exposure": nodes.exposure_node,
    "scenario": nodes.scenario_node,
    "risk": nodes.risk_node,
    "drivers": nodes.drivers_node,
    "fusion": nodes.fusion_node,
    "hedging": nodes.hedging_node,
}


@lru_cache(maxsize=1)
def get_graph():
    g = StateGraph(PipelineState)
    g.add_node("understand", nodes.understand_node)
    for name, fn in _AGENT_NODES.items():
        g.add_node(name, fn)
    g.add_node("finalize", nodes.finalize_node)

    g.add_edge(START, "understand")
    targets = {**{name: name for name in _AGENT_NODES}, "finalize": "finalize"}
    g.add_conditional_edges("understand", nodes.route, targets)
    for name in _AGENT_NODES:
        g.add_conditional_edges(name, nodes.route, targets)  # back to the router after every agent
    g.add_edge("finalize", END)
    return g.compile()


def _ordered(runs: list[AgentRun]) -> list[AgentRun]:
    order = {s: i for i, s in enumerate(nodes.STEP_ORDER)}
    return sorted(runs, key=lambda r: order[r.step])


def run_pipeline(query: str) -> QueryPipelineResponse:
    """`query` must already be sanitised (QueryIn does this)."""
    final = get_graph().invoke({"query": query})
    parse = final["parse"]
    return QueryPipelineResponse(
        query=parse.query, parsed=parse.parsed, parse_notice=parse.notice,
        weather=final.get("weather"), news=final.get("news"), market=final.get("market"),
        historical=final.get("historical"), exposure=final.get("exposure"), scenario=final.get("scenario"), risk=final.get("risk"),
        drivers=final.get("drivers"), fusion=final.get("fusion"), hedging=final.get("hedging"),
        steps=_ordered(final.get("runs", [])),
    )


def _merge(state: dict, update: dict) -> None:
    """Apply a node's partial update the way LangGraph does: `runs` is append-only, everything else is replaced."""
    for k, v in update.items():
        state[k] = (state.get(k, []) + v) if k == "runs" else v


def _response(state: dict) -> QueryPipelineResponse:
    parse = state["parse"]
    return QueryPipelineResponse(
        query=parse.query, parsed=parse.parsed, parse_notice=parse.notice,
        weather=state.get("weather"), news=state.get("news"), market=state.get("market"),
        historical=state.get("historical"), exposure=state.get("exposure"), scenario=state.get("scenario"), risk=state.get("risk"),
        drivers=state.get("drivers"), fusion=state.get("fusion"), hedging=state.get("hedging"),
        steps=_ordered(state.get("runs", [])),
    )


def stream_pipeline(query: str) -> Iterator[dict]:
    """The same run as `run_pipeline`, reported as it happens (one dict per real event; nothing is simulated).

    Events: start -> plan (after Query Understanding) -> [step_start, step_done]* -> result
    Durations are measured wall-clock time between the graph's own node-completion events. "step_start" for the next step is
    emitted the moment the previous node finishes, which is exactly when the graph's router hands control to it (execution is
    sequential), so the "active" step shown to the user is the step that is really running.
    """
    t0 = last = time.perf_counter()
    state: dict = {}
    yield {"type": "start", "query": query}
    try:
        for chunk in get_graph().stream({"query": query}, stream_mode="updates"):
            for node, update in chunk.items():
                now = time.perf_counter()
                dur_ms, last = int((now - last) * 1000), now
                if update:
                    _merge(state, update)
                if node == "understand":
                    p = state["parse"]
                    yield {"type": "plan", "duration_ms": dur_ms, "parsed": p.parsed.model_dump(mode="json"), "notice": p.notice,
                           "steps": [s for s in state["pending"] if s in nodes.IMPLEMENTED],
                           "skipped": [s for s in state["pending"] if s not in nodes.IMPLEMENTED]}
                elif node in _AGENT_NODES:
                    run = (update or {}).get("runs", [None])[0]
                    yield {"type": "step_done", "step": node, "status": run.status if run else "completed",
                           "note": run.note if run else None, "duration_ms": dur_ms}
                if node != "finalize" and state.get("pending") is not None:
                    nxt = nodes.route(state)
                    if nxt != "finalize":
                        yield {"type": "step_start", "step": nxt}
        yield {"type": "result", "total_ms": int((time.perf_counter() - t0) * 1000), "data": _response(state).model_dump(mode="json")}
    except Exception as e:  # noqa: BLE001  (a safe message only; details stay in the server log)
        import logging
        logging.getLogger("finsight.graph").error("stream pipeline failed: %s", type(e).__name__)
        yield {"type": "error", "message": "The analysis could not be completed."}
