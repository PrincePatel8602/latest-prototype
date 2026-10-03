"use client";

import { motion } from "motion/react";
import { Check, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ICONS } from "@/components/pipeline/PipelineView";
import { Badge, Button, Card, Dot, Kv } from "@/components/ui/ui";
import { useWidth } from "@/hooks/useMeasure";
import { AGENTS, INTENT_LABEL, LANES, STEP_ORDER, type StepKey } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { duration, timeAgo } from "@/lib/format";
import type { HistoryEntry } from "@/lib/history";

type NodeId = "question" | "understand" | "report" | StepKey;
type NState = "idle" | "waiting" | "active" | "done" | "failed" | "skipped";

const FIXED: Record<"question" | "understand" | "report", { title: string; sub: string; does: string; technical: string; sources: string[] }> = {
  question: { title: "Question", sub: "Plain English", does: "Anything you can ask a colleague: about a storm, your risk, a hedge or a year in history.", technical: "Sanitised and limited to 500 characters before anything else happens.", sources: [] },
  understand: { title: "Understanding", sub: "Goal · event · place · period", does: "Works out what you are asking and which specialists are needed, including whether it is about your holdings or about the past.",
    technical: "Query Understanding: an LLM (Gemini) returns structured fields that are validated by a strict gate; a rule-based parser is the fallback. Past-period questions are routed to history only.", sources: ["Gemini", "Rules fallback"] },
  report: { title: "Report", sub: "Finding · evidence · detail", does: "The finding first, then the evidence behind it, then the technical detail for anyone who wants to check.", technical: "Insights are assembled by deterministic rules from the agents’ real outputs; no text is generated.", sources: [] },
};

// Geometry of the map (px). It is scaled to fit its container; below 1024px a list view is used instead.
const W = 1100, H = 440, NODE_H = 66, GAP = 14;
const COL = { question: [0, 104], understand: [128, 156], gather: [312, 196], analyze: [548, 196], synthesize: [784, 176], report: [990, 110] } as const;
const laneNodes = (lane: string) => STEP_ORDER.filter((k) => AGENTS[k].lane === lane);
const colY = (n: number, i: number) => H / 2 - (n * NODE_H + (n - 1) * GAP) / 2 + i * (NODE_H + GAP);

function pos(id: NodeId): { x: number; y: number; w: number; h: number } {
  if (id === "question") return { x: COL.question[0], y: H / 2 - 44, w: COL.question[1], h: 88 };
  if (id === "understand") return { x: COL.understand[0], y: H / 2 - 44, w: COL.understand[1], h: 88 };
  if (id === "report") return { x: COL.report[0], y: H / 2 - 44, w: COL.report[1], h: 88 };
  const lane = AGENTS[id].lane, list = laneNodes(lane), i = list.indexOf(id), [x, w] = COL[lane];
  return { x, y: colY(list.length, i), w, h: NODE_H };
}

const STATE_STYLE: Record<NState, string> = {
  idle: "border-line-soft", waiting: "border-line-soft opacity-60", active: "border-accent shadow-[0_0_0_4px_rgba(110,168,255,0.1)]",
  done: "border-line", failed: "border-down/60", skipped: "border-line-soft opacity-40",
};

function MapNode({ id, st, ms, selected, onSelect }: { id: NodeId; st: NState; ms?: number; selected: boolean; onSelect: () => void }) {
  const a = id in AGENTS ? AGENTS[id as StepKey] : null, fx = !a ? FIXED[id as keyof typeof FIXED] : null;
  const Icon = a ? ICONS[a.key] : null;
  return (
    <button type="button" onClick={onSelect} onFocus={onSelect} aria-pressed={selected} aria-label={`${a?.title ?? fx!.title}: ${st}`}
      className={cn("group relative flex h-full w-full flex-col justify-center overflow-hidden rounded-2xl border bg-surface px-3.5 text-left transition-[border-color,box-shadow,opacity] duration-500 hover:border-subtle",
        STATE_STYLE[st], selected && "!border-accent/70 bg-surface-2")}>
      <span className="flex items-center gap-2">
        {Icon && <Icon className={cn("h-3.5 w-3.5 shrink-0", st === "active" || st === "done" ? "text-accent" : "text-subtle")} />}
        <span className="truncate text-[13px] font-medium text-ink">{a?.title ?? fx!.title}</span>
        <span className="ml-auto shrink-0">{st === "active" ? <Dot tone="accent" pulse /> : st === "done" ? <Check className="h-3 w-3 text-up" /> : st === "failed" ? <Dot tone="down" /> : null}</span>
      </span>
      <span className="mt-1 truncate text-[11px] text-subtle">{st === "done" && ms != null && <><span className="num text-muted">{duration(ms)}</span> · </>}{a ? a.sources.join(" · ") : fx!.sub}</span>
      {st === "active" && <span className="flow-line absolute inset-x-0 bottom-0" />}
    </button>
  );
}

function useReplay(entry: HistoryEntry | null) {
  const [t, setT] = useState<{ step: number; running: boolean } | null>(null);   // step: -2 question, -1 understanding, 0.. agents, n report
  const timers = useRef<number[]>([]);
  const order = useMemo(() => (entry ? entry.data.steps.map((s) => s.step).filter((k): k is StepKey => (STEP_ORDER as string[]).includes(k)) : []), [entry]);
  const speed = useMemo(() => (entry ? Math.max(1, entry.totalMs / 9000) : 1), [entry]);
  const stop = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => stop, []);
  const play = useCallback(() => {
    if (!entry) return;
    stop();
    const seq: { step: number; wait: number }[] = [{ step: -2, wait: 350 }, { step: -1, wait: Math.max(400, entry.planMs / speed) }];
    order.forEach((k, i) => seq.push({ step: i, wait: Math.max(280, Math.min(1500, (entry.stepMs[k] ?? 300) / speed)) }));
    seq.push({ step: order.length, wait: 0 });
    let at = 0;
    setT({ step: -3, running: true });
    seq.forEach((s, i) => { timers.current.push(window.setTimeout(() => setT({ step: s.step, running: i < seq.length - 1 }), at)); at += s.wait; });
  }, [entry, order, speed]);
  const states = useMemo(() => {
    const m: Record<string, NState> = {};
    [...STEP_ORDER, "question", "understand", "report"].forEach((k) => (m[k] = entry ? "skipped" : "idle"));
    if (!entry) return m;
    const failed = new Set(entry.data.steps.filter((s) => s.status === "failed").map((s) => s.step));
    const final = (k: StepKey): NState => (failed.has(k) ? "failed" : "done");
    // t.step: -3 just started, -2 question, -1 understanding, 0..n-1 the agents in the order they really ran, n = finished
    m.question = !t ? "done" : t.step <= -3 ? "waiting" : t.step === -2 ? "active" : "done";
    m.understand = !t ? "done" : t.step <= -2 ? "waiting" : t.step === -1 ? "active" : "done";
    order.forEach((k, i) => { m[k] = !t || t.step > i ? final(k) : t.step === i ? "active" : "waiting"; });
    m.report = !t || t.step >= order.length ? "done" : "waiting";
    return m;
  }, [entry, t, order]);
  return { states, play, replaying: !!t?.running, speed, reset: () => { stop(); setT(null); } };
}

export default function SystemMap({ entry }: { entry: HistoryEntry | null }) {
  const [wrap, width] = useWidth<HTMLDivElement>(1100);
  const [sel, setSel] = useState<NodeId>("understand");
  const { states, play, replaying, speed, reset } = useReplay(entry);
  const scale = Math.min(1.12, width / W);
  const list = width < 1000;

  // edges between adjacent columns (soft bundles); animated while the downstream column is the one working
  const edges: [string, number, number, number, number, NodeId[]][] = useMemo(() => {
    const mid = H / 2;
    return [
      ["q", COL.question[0] + COL.question[1], mid, COL.understand[0], mid, ["understand"]],
      ["u", COL.understand[0] + COL.understand[1], mid, COL.gather[0] - 14, mid, laneNodes("gather")],
      ["g", COL.gather[0] + COL.gather[1] + 14, mid, COL.analyze[0] - 14, mid, laneNodes("analyze")],
      ["a", COL.analyze[0] + COL.analyze[1] + 14, mid, COL.synthesize[0] - 14, mid, laneNodes("synthesize")],
      ["s", COL.synthesize[0] + COL.synthesize[1] + 14, mid, COL.report[0], mid, ["report"]],
    ];
  }, []);

  const stateOf = (id: NodeId) => states[id] as NState;
  const msOf = (id: NodeId): number | undefined => (entry ? (id === "understand" ? entry.planMs : id === "report" ? undefined : entry.stepMs[id]) : undefined);
  const info = sel in AGENTS ? { ...AGENTS[sel as StepKey], sub: "" } : { ...FIXED[sel as keyof typeof FIXED], key: sel, lane: "" };
  const run = entry?.data.steps.find((s) => s.step === sel);

  const detail = (
    <Card className="p-6 sm:p-8">
      <div className="flex flex-wrap items-center gap-2"><p className="h3">{info.title}</p>{stateOf(sel) === "done" && <Badge tone="up">Ran in your last analysis</Badge>}{stateOf(sel) === "skipped" && <Badge>Not needed for your last question</Badge>}{stateOf(sel) === "failed" && <Badge tone="down">Failed in your last analysis</Badge>}</div>
      <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-2">{info.does}</p>
      <dl className="mt-5">
        <Kv k="How it works">{info.technical}</Kv>
        {info.sources.length > 0 && <Kv k="Reads from">{info.sources.join(", ")}</Kv>}
        {sel === "understand" && entry && <Kv k="Last run">{entry.data.parsed.parser === "llm" ? `Understood by ${entry.data.parsed.llm_model}` : "Rule-based parser"} · {INTENT_LABEL[entry.data.parsed.intent]} · {duration(entry.planMs)}</Kv>}
        {run && <Kv k="Last result">{run.note ?? "Completed"} {entry!.stepMs[sel] != null && <span className="num text-subtle">· {duration(entry!.stepMs[sel])}</span>}</Kv>}
      </dl>
    </Card>
  );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">
          {entry ? <>Showing your last analysis, “<span className="text-ink-2">{entry.query}</span>” <span className="text-subtle">· {timeAgo(entry.createdAt)}</span></> : "Click any step to see what it does. Run an analysis to light up the map with real results."}
        </p>
        {entry ? (
          <div className="flex items-center gap-2">
            {replaying && <span className="text-xs text-subtle">recorded timings, ×{speed.toFixed(1)} speed</span>}
            <Button variant="ghost" onClick={replaying ? reset : play} className="!h-9 !px-4 text-[13px]">{replaying ? <><RotateCcw className="h-3.5 w-3.5" /> Stop</> : <><Play className="h-3.5 w-3.5" /> Replay it</>}</Button>
          </div>
        ) : <Button href="/ask" variant="ghost" className="!h-9 !px-4 text-[13px]">Run an analysis</Button>}
      </div>

      {list ? (
        <div className="space-y-6">
          {([{ id: "question" as const, title: "Start" }, ...LANES.map((l) => ({ id: l.id, title: l.title }))]).map((g) => (
            <div key={g.id}>
              <p className="eyebrow mb-2">{g.title}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {(g.id === "question" ? (["question", "understand"] as NodeId[]) : laneNodes(g.id)).map((id) => <div key={id} className="h-16"><MapNode id={id} st={stateOf(id)} ms={msOf(id)} selected={sel === id} onSelect={() => setSel(id)} /></div>)}
              </div>
            </div>
          ))}
          <div><p className="eyebrow mb-2">Finish</p><div className="h-16 sm:w-1/2"><MapNode id="report" st={stateOf("report")} selected={sel === "report"} onSelect={() => setSel("report")} /></div></div>
        </div>
      ) : (
        <div ref={wrap} style={{ height: H * scale }} className="relative overflow-hidden">
          <div style={{ width: W, height: H, transform: `scale(${scale})`, transformOrigin: "top left", marginLeft: Math.max(0, (width - W * scale) / 2) }} className="relative">
            {LANES.map((l) => {
              const [x, w] = COL[l.id], n = laneNodes(l.id).length, top = colY(n, 0) - 34;
              return (
                <div key={l.id} className="absolute rounded-3xl border border-line-soft bg-bg-elev/60" style={{ left: x - 10, width: w + 20, top, height: n * NODE_H + (n - 1) * GAP + 48 }}>
                  <p className="eyebrow !text-[0.62rem] absolute left-4 top-3">{l.title}</p>
                </div>
              );
            })}
            <svg width={W} height={H} className="absolute inset-0" aria-hidden>
              {edges.map(([id, x1, y1, x2, y2, targets]) => {
                const live = targets.some((t) => stateOf(t) === "active"), lit = targets.some((t) => stateOf(t) === "done" || stateOf(t) === "active");
                return (
                  <g key={id}>
                    <path d={`M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`} fill="none" stroke={lit ? "#6ea8ff" : "#232834"} strokeOpacity={lit ? 0.55 : 1} strokeWidth={lit ? 1.6 : 1.2} />
                    {live && <motion.circle r={3.5} fill="#6ea8ff" initial={{ cx: x1, cy: y1 }} animate={{ cx: [x1, x2], cy: [y1, y2] }} transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }} />}
                  </g>
                );
              })}
            </svg>
            {(["question", "understand", "report", ...STEP_ORDER] as NodeId[]).map((id) => {
              const p = pos(id);
              return <div key={id} className="absolute" style={{ left: p.x, top: p.y, width: p.w, height: p.h }}><MapNode id={id} st={stateOf(id)} ms={msOf(id)} selected={sel === id} onSelect={() => setSel(id)} /></div>;
            })}
          </div>
        </div>
      )}

      <div className="mt-6">{detail}</div>
    </div>
  );
}
