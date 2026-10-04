"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { STEP_ORDER, type StepKey } from "@/lib/agents";
import { saveRun, type HistoryEntry } from "@/lib/history";
import { streamQuery, type StreamEvent } from "@/lib/stream";
import type { QueryPipelineResponse } from "@/types/agents";
import type { ParsedQuery } from "@/types/query";

export type StepStatus = "waiting" | "active" | "done" | "failed";
export interface StepState { key: StepKey; status: StepStatus; durationMs?: number; note?: string | null }
export interface RunState {
  phase: "idle" | "understanding" | "running" | "done" | "error";
  query: string; parsed?: ParsedQuery; parseNotice?: string | null; planMs?: number;
  steps: StepState[]; result?: QueryPipelineResponse; totalMs?: number; error?: string; saved?: HistoryEntry | null;
}

const IDLE: RunState = { phase: "idle", query: "", steps: [] };

type Action = { type: "begin"; query: string } | { type: "event"; e: StreamEvent } | { type: "fail"; message: string } | { type: "saved"; entry: HistoryEntry | null } | { type: "reset" };

function reducer(s: RunState, a: Action): RunState {
  switch (a.type) {
    case "begin": return { phase: "understanding", query: a.query, steps: [] };
    case "reset": return IDLE;
    case "fail": return { ...s, phase: "error", error: a.message };
    case "saved": return { ...s, saved: a.entry };
    case "event": {
      const e = a.e;
      if (e.type === "plan") {
        const keys = e.steps.filter((x): x is StepKey => (STEP_ORDER as string[]).includes(x));
        return { ...s, phase: "running", parsed: e.parsed, parseNotice: e.notice, planMs: e.duration_ms, steps: keys.map((key) => ({ key, status: "waiting" as const })) };
      }
      if (e.type === "step_start") return { ...s, steps: s.steps.map((x) => (x.key === e.step ? { ...x, status: "active" } : x)) };
      if (e.type === "step_done")
        return { ...s, steps: s.steps.map((x) => (x.key === e.step ? { ...x, status: e.status === "failed" ? "failed" : "done", durationMs: e.duration_ms, note: e.note } : x)) };
      if (e.type === "result") return { ...s, phase: "done", result: e.data, totalMs: e.total_ms };
      if (e.type === "error") return { ...s, phase: "error", error: e.message };
      return s;
    }
  }
}

/** Runs one analysis and exposes its REAL progress: the plan, each agent's start/finish, measured durations, then the result. */
export function useAnalysis() {
  const [state, dispatch] = useReducer(reducer, IDLE);
  const abort = useRef<AbortController | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const run = useCallback(async (query: string) => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    dispatch({ type: "begin", query });
    const stepMs: Record<string, number> = {};
    let planMs = 0;
    try {
      for await (const e of streamQuery(query, ctl.signal)) {
        if (ctl.signal.aborted) return;
        if (e.type === "plan") planMs = e.duration_ms;
        if (e.type === "step_done") stepMs[e.step] = e.duration_ms;
        dispatch({ type: "event", e });
        if (e.type === "result") dispatch({ type: "saved", entry: saveRun({ data: e.data, totalMs: e.total_ms, planMs, stepMs }) });
      }
    } catch (err) {
      if (!ctl.signal.aborted) dispatch({ type: "fail", message: err instanceof Error ? err.message : "Something went wrong." });
    }
  }, []);

  const reset = useCallback(() => { abort.current?.abort(); dispatch({ type: "reset" }); }, []);
  useEffect(() => () => abort.current?.abort(), []);
  return { state, run, reset };
}

/** Rebuilds a finished run from a saved history entry, so the same pipeline view can replay it (real recorded timings and notes). */
export function runFromEntry(e: HistoryEntry): RunState {
  const keys = e.data.steps.map((s) => s.step).filter((x): x is StepKey => (STEP_ORDER as string[]).includes(x));
  return {
    phase: "done", query: e.query, parsed: e.data.parsed, parseNotice: e.data.parse_notice, planMs: e.planMs, totalMs: e.totalMs, result: e.data, saved: e,
    steps: keys.map((key) => {
      const r = e.data.steps.find((s) => s.step === key);
      return { key, status: r?.status === "failed" ? "failed" : "done", durationMs: e.stepMs[key], note: r?.note };
    }),
  };
}
