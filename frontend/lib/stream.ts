import { API_URL } from "@/lib/api";
import type { QueryPipelineResponse } from "@/types/agents";
import type { ParsedQuery } from "@/types/query";

// Events emitted by POST /api/query/stream. Every one corresponds to something the backend really did.
export type StreamEvent =
  | { type: "start"; query: string }
  | { type: "plan"; duration_ms: number; parsed: ParsedQuery; notice: string | null; steps: string[]; skipped: string[] }
  | { type: "step_start"; step: string }
  | { type: "step_done"; step: string; status: "completed" | "failed"; note: string | null; duration_ms: number }
  | { type: "result"; total_ms: number; data: QueryPipelineResponse }
  | { type: "error"; message: string };

export class BackendUnreachable extends Error {}

export async function* streamQuery(query: string, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/query/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query }), signal,
    });
  } catch (e) {
    if (signal?.aborted) return;
    throw new BackendUnreachable("The FinSight backend can't be reached. Check that the API is running and try again.");
  }
  if (res.status === 422) throw new Error("That question wasn't accepted. Please use between 3 and 500 characters.");
  if (!res.ok || !res.body) throw new Error(`The analysis service returned an error (${res.status}).`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) yield JSON.parse(line) as StreamEvent;
      }
    }
    if (buf.trim()) yield JSON.parse(buf) as StreamEvent;
  } catch (e) {
    if (signal?.aborted) return;
    throw new BackendUnreachable("The connection to the analysis service was interrupted.");
  }
}
