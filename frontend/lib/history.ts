import { buildInsights } from "@/lib/insight";
import type { QueryPipelineResponse } from "@/types/agents";

// Past analyses are kept in this browser only (localStorage). Nothing is sent anywhere.
const KEY = "finsight.history.v1";
const MAX = 12;

export interface HistoryEntry {
  id: string; query: string; createdAt: string; headline: string; intent: string; totalMs: number; planMs: number;
  stepMs: Record<string, number>; stepStatus: Record<string, string>; data: QueryPipelineResponse;
}

const safe = <T,>(fn: () => T, fallback: T): T => { try { return fn(); } catch { return fallback; } };

export function loadHistory(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  return safe(() => JSON.parse(window.localStorage.getItem(KEY) ?? "[]") as HistoryEntry[], []);
}

export function saveRun(args: { data: QueryPipelineResponse; totalMs: number; planMs: number; stepMs: Record<string, number> }): HistoryEntry | null {
  if (typeof window === "undefined") return null;
  const entry: HistoryEntry = {
    id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, query: args.data.query, createdAt: new Date().toISOString(),
    headline: buildInsights(args.data).primary.headline, intent: args.data.parsed.intent, totalMs: args.totalMs, planMs: args.planMs, stepMs: args.stepMs,
    stepStatus: Object.fromEntries(args.data.steps.map((s) => [s.step, s.status])), data: args.data,
  };
  let list = [entry, ...loadHistory()].slice(0, MAX);
  // localStorage is small: drop the oldest entries until the write succeeds
  while (list.length && !safe(() => (window.localStorage.setItem(KEY, JSON.stringify(list)), true), false)) list = list.slice(0, -1);
  return list.length ? entry : null;
}

export const getEntry = (id: string) => loadHistory().find((e) => e.id === id) ?? null;
export const latestEntry = () => loadHistory()[0] ?? null;
export const removeEntry = (id: string) => safe(() => window.localStorage.setItem(KEY, JSON.stringify(loadHistory().filter((e) => e.id !== id))), undefined);
export const clearHistory = () => safe(() => window.localStorage.removeItem(KEY), undefined);
