"""LangGraph nodes. Each one is a thin wrapper: the real logic lives in app/agents/*.

A node never lets an exception escape: a broken agent becomes a `failed` AgentRun and the
rest of the pipeline keeps going.
"""
import logging
from typing import Any, Callable

from app.agents.market_agent import run_market_agent
from app.agents.historical_agent import run_historical_agent
from app.agents.quant_agent import run_drivers_agent, run_exposure_agent, run_fusion_agent, run_hedging_agent, run_scenario_agent, run_risk_agent
from app.agents.news_agent import run_news_agent
from app.agents.query_understanding import understand_query
from app.agents.weather_agent import run_weather_agent
from app.graph.state import PipelineState
from app.schemas.pipeline import AgentRun
from app.schemas.query import AnalysisStep, ParsedQuery

log = logging.getLogger("finsight.graph")

# Canonical pipeline order (matches the AnalysisStep literal in schemas/query.py).
STEP_ORDER: tuple[str, ...] = (
    "weather", "news", "market", "historical", "exposure", "scenario", "risk", "drivers", "fusion", "hedging",
)
# Steps that have an agent today. Everything else is reported as not_implemented.
IMPLEMENTED: tuple[str, ...] = ("weather", "news", "market", "historical", "exposure", "scenario", "risk", "drivers", "fusion", "hedging")

NOT_IMPLEMENTED_NOTE = "Not implemented yet - this step belongs to a later phase."


def understand_node(state: PipelineState) -> dict[str, Any]:
    """Query Understanding (LLM with rule-based fallback - unchanged)."""
    parse = understand_query(state["query"])
    wanted = set(parse.parsed.analysis_steps)
    return {"parse": parse, "pending": [s for s in STEP_ORDER if s in wanted], "runs": []}


def _agent_node(step: str, agent: Callable[[ParsedQuery], Any]) -> Callable[[PipelineState], dict[str, Any]]:
    def node(state: PipelineState) -> dict[str, Any]:
        parsed = state["parse"].parsed
        remaining = [s for s in state["pending"] if s != step]
        step_name: AnalysisStep = step  # type: ignore[assignment]
        try:
            result = agent(parsed)
        except Exception as e:  # noqa: BLE001
            log.error("%s agent crashed: %s", step, type(e).__name__)
            run = AgentRun(step=step_name, status="failed", note="Agent failed unexpectedly.")
            return {step: None, "pending": remaining, "runs": [run]}
        failed = getattr(result, "status", None) == "error"
        note = result.summary if not failed else (result.notices[0] if getattr(result, "notices", None) else None)
        run = AgentRun(step=step_name, status="failed" if failed else "completed", note=note)
        return {step: result, "pending": remaining, "runs": [run]}
    return node


weather_node = _agent_node("weather", run_weather_agent)
news_node = _agent_node("news", run_news_agent)
market_node = _agent_node("market", run_market_agent)
historical_node = _agent_node("historical", run_historical_agent)
exposure_node = _agent_node("exposure", run_exposure_agent)

def scenario_node(state: PipelineState) -> dict[str, Any]:
    step = "scenario"
    parsed = state["parse"].parsed
    remaining = [s for s in state["pending"] if s != step]
    try:
        result = run_scenario_agent(parsed)
        run = AgentRun(step=step, status="completed", note=result.summary)
        return {"scenario": result, "pending": remaining, "runs": [run]}
    except Exception as e:  # noqa: BLE001
        log.error("%s agent crashed: %s", step, type(e).__name__)
        return {"scenario": None, "pending": remaining, "runs": [AgentRun(step=step, status="failed", note="Agent failed unexpectedly.")]}

def risk_node(state: PipelineState) -> dict[str, Any]:
    step = "risk"
    parsed = state["parse"].parsed
    remaining = [s for s in state["pending"] if s != step]
    try:
        result = run_risk_agent(parsed, state.get("scenario"))
        return {"risk": result, "pending": remaining, "runs": [AgentRun(step=step, status="completed", note=result.summary)]}
    except Exception as e:  # noqa: BLE001
        log.error("%s agent crashed: %s", step, type(e).__name__)
        return {"risk": None, "pending": remaining, "runs": [AgentRun(step=step, status="failed", note="Agent failed unexpectedly.")]}


def drivers_node(state: PipelineState) -> dict[str, Any]:
    step = "drivers"
    parsed = state["parse"].parsed
    remaining = [s for s in state["pending"] if s != step]
    try:
        result = run_drivers_agent(parsed, weather=state.get("weather"), news=state.get("news"), market=state.get("market"))
        return {"drivers": result, "pending": remaining, "runs": [AgentRun(step=step, status="completed", note=result.conclusion)]}
    except Exception as e:  # noqa: BLE001
        log.error("%s agent crashed: %s", step, type(e).__name__)
        return {"drivers": None, "pending": remaining, "runs": [AgentRun(step=step, status="failed", note="Agent failed unexpectedly.")]}


def hedging_node(state: PipelineState) -> dict[str, Any]:
    step = "hedging"
    parsed = state["parse"].parsed
    remaining = [s for s in state["pending"] if s != step]
    try:
        result = run_hedging_agent(parsed, risk=state.get("risk"))
        return {"hedging": result, "pending": remaining, "runs": [AgentRun(step=step, status="completed", note=result.conclusion)]}
    except Exception as e:  # noqa: BLE001
        log.error("%s agent crashed: %s", step, type(e).__name__)
        return {"hedging": None, "pending": remaining, "runs": [AgentRun(step=step, status="failed", note="Agent failed unexpectedly.")]}


def fusion_node(state: PipelineState) -> dict[str, Any]:
    """Fusion reads what earlier agents produced (as context + the scenario assumptions it compares against history)."""
    step = "fusion"
    parsed = state["parse"].parsed
    remaining = [s for s in state["pending"] if s != step]
    try:
        result = run_fusion_agent(parsed, weather=state.get("weather"), news=state.get("news"),
                                  market=state.get("market"), scenario=state.get("scenario"))
        run = AgentRun(step=step, status="completed", note=result.conclusion)    # "unavailable"/"insufficient" are explained in the note
        return {"fusion": result, "pending": remaining, "runs": [run]}
    except Exception as e:  # noqa: BLE001
        log.error("%s agent crashed: %s", step, type(e).__name__)
        return {"fusion": None, "pending": remaining, "runs": [AgentRun(step=step, status="failed", note="Agent failed unexpectedly.")]}


def route(state: PipelineState) -> str:
    """Conditional edge: the next implemented step that is still pending, else 'finalize'."""
    for step in state["pending"]:
        if step in IMPLEMENTED:
            return step
    return "finalize"


def finalize_node(state: PipelineState) -> dict[str, Any]:
    """Whatever is still pending has no agent yet: say so explicitly (never fake a result)."""
    runs = [AgentRun(step=s, status="not_implemented", note=NOT_IMPLEMENTED_NOTE)  # type: ignore[arg-type]
            for s in state["pending"]]
    return {"pending": [], "runs": runs}


