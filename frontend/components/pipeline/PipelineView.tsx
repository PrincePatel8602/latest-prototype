"use client";

import { motion } from "motion/react";
import {
  Activity, Check, CloudLightning, FlaskConical, History, Newspaper, PieChart, Scale, ShieldAlert, ShieldCheck, TrendingUp, X,
} from "lucide-react";
import type { ComponentType } from "react";
import type { RunState, StepState } from "@/hooks/useAnalysis";
import { AGENTS, INTENT_LABEL, LANES, STEP_ORDER, type StepKey } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { duration } from "@/lib/format";
import { Badge, Dot } from "@/components/ui/ui";

export const ICONS: Record<StepKey, ComponentType<{ className?: string }>> = {
  weather: CloudLightning, news: Newspaper, market: TrendingUp, historical: History, exposure: PieChart,
  scenario: FlaskConical, risk: ShieldAlert, drivers: Activity, fusion: Scale, hedging: ShieldCheck,
};

type Stage = "waiting" | "active" | "done";

function stages(run: RunState): [Stage, Stage, Stage, Stage] {
  const planned = run.phase !== "understanding" && run.phase !== "idle";
  const finished = run.steps.length > 0 && run.steps.every((s) => s.status === "done" || s.status === "failed");
  const done = run.phase === "done";
  return [
    run.phase === "idle" ? "waiting" : "done",
    run.phase === "understanding" ? "active" : planned ? "done" : "waiting",
    done || (planned && finished) ? "done" : planned ? "active" : "waiting",
    done ? "done" : planned && finished ? "active" : "waiting",
  ];
}

function StageDot({ n, s }: { n: number; s: Stage }) {
  return (
    <span className={cn("relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border text-xs font-semibold transition-colors duration-500",
      s === "done" && "border-accent/50 bg-accent/15 text-accent", s === "active" && "border-accent bg-accent text-bg", s === "waiting" && "border-line bg-bg text-subtle")}>
      {s === "done" ? <Check className="h-4 w-4" /> : n}
      {s === "active" && <span className="absolute inset-0 -z-10 animate-ping rounded-full bg-accent/30 motion-reduce:hidden" />}
    </span>
  );
}

function Connector({ from, to }: { from: Stage; to: Stage }) {
  return (
    <span aria-hidden className="absolute left-4 top-8 -z-0 h-[calc(100%+1rem)] w-px bg-line md:left-10 md:right-[-1rem] md:top-4 md:h-px md:w-auto">
      <span className={cn("absolute inset-0 origin-left bg-accent/60 transition-transform duration-700 md:origin-left", from === "done" ? "scale-100" : "scale-0")} />
      {from === "done" && to === "active" && <span className="flow-line absolute inset-x-0 top-1/2 -translate-y-1/2" />}
    </span>
  );
}

function AgentNode({ info, st }: { info: (typeof AGENTS)[StepKey]; st: StepState }) {
  const Icon = ICONS[info.key];
  const tone = st.status === "done" ? "border-line" : st.status === "active" ? "border-accent/60 shadow-[0_0_0_4px_rgba(110,168,255,0.08)]" : st.status === "failed" ? "border-down/50" : "border-line-soft opacity-70";
  return (
    <motion.li layout="position" initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: st.status === "waiting" ? 0.7 : 1, y: 0, scale: 1 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className={cn("relative overflow-hidden rounded-2xl border bg-surface/80 p-4 transition-[border-color,box-shadow] duration-500", tone)}>
      <div className="flex items-start gap-3">
        <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-xl border transition-colors duration-500",
          st.status === "active" ? "border-accent/40 bg-accent/10 text-accent" : st.status === "done" ? "border-line text-ink-2" : st.status === "failed" ? "border-down/40 text-down" : "border-line-soft text-subtle")}>
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-ink">{info.title}</p>
            <StatusChip st={st} />
          </div>
          <p className="mt-1 text-[13px] leading-snug text-muted">{info.does}</p>
          {st.status === "done" && st.note && <p className="mt-2 line-clamp-2 text-xs leading-snug text-ink-2" title={st.note}>{st.note}</p>}
          {st.status === "failed" && <p className="mt-2 text-xs text-down">This agent failed and was skipped. The rest of the analysis continued.</p>}
        </div>
      </div>
      {st.status === "active" && <span className="flow-line absolute inset-x-0 bottom-0" />}
    </motion.li>
  );
}

function StatusChip({ st }: { st: StepState }) {
  if (st.status === "active") return <span className="flex items-center gap-1.5 text-xs text-accent"><Dot tone="accent" pulse />Working</span>;
  if (st.status === "done") return <span className="num flex items-center gap-1.5 text-xs text-muted"><Check className="h-3 w-3 text-up" />{duration(st.durationMs)}</span>;
  if (st.status === "failed") return <span className="flex items-center gap-1 text-xs text-down"><X className="h-3 w-3" />Failed</span>;
  return <span className="text-xs text-subtle">Waiting</span>;
}

export default function PipelineView({ run, live }: { run: RunState; live?: boolean }) {
  const [s1, s2, s3, s4] = stages(run);
  const p = run.parsed;
  const doneCount = run.steps.filter((s) => s.status === "done" || s.status === "failed").length;
  const notNeeded = STEP_ORDER.filter((k) => !run.steps.some((s) => s.key === k));
  const lanes = LANES.map((l) => ({ ...l, steps: run.steps.filter((s) => AGENTS[s.key].lane === l.id) })).filter((l) => l.steps.length);

  const period = p?.year_from != null ? (p.year_from === p.year_to ? String(p.year_from) : `${p.year_from ?? "…"}–${p.year_to ?? "…"}`) : null;
  const chips = p ? [
    ["Goal", INTENT_LABEL[p.intent] ?? p.intent], p.event_type !== "none" ? ["Event", p.event_type.replace("_", " ")] : null,
    p.event_category ? ["Strength", `Category ${p.event_category}`] : null, p.region ? ["Place", p.region] : null, period ? ["Period", period] : null,
    ["Scope", p.uses_portfolio ? "Your portfolio" : "General"],
  ].filter(Boolean) as [string, string][] : [];

  const items: { n: number; title: string; s: Stage; from: Stage; to: Stage; body: React.ReactNode }[] = [
    { n: 1, title: "Your question", s: s1, from: s1, to: s2, body: <p className="text-sm leading-snug text-ink-2">“{run.query}”</p> },
    { n: 2, title: "Understanding", s: s2, from: s2, to: s3, body: s2 === "active"
        ? <p className="text-sm text-muted">Working out what you are asking and which agents are needed…</p>
        : p ? (
          <div>
            <div className="flex flex-wrap gap-1.5">{chips.map(([k, v]) => <Badge key={k} tone="neutral"><span className="text-subtle">{k}</span> {v}</Badge>)}</div>
            <p className="mt-2 text-xs text-subtle">{p.parser === "llm" ? `Understood by ${p.llm_model ?? "an AI model"}` : "Understood by the rule-based parser"} · <span className="num">{duration(run.planMs)}</span></p>
            {run.parseNotice && <p className="mt-1 text-xs text-warn/90">{run.parseNotice.replace(/\s+/g, " ")}</p>}
          </div>) : <p className="text-sm text-subtle">Waiting</p> },
    { n: 3, title: "Agents", s: s3, from: s3, to: s4, body: run.steps.length ? (
        <div>
          <p className="text-sm text-ink-2"><span className="num">{doneCount}</span> of <span className="num">{run.steps.length}</span> finished</p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-line-soft"><div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${(doneCount / run.steps.length) * 100}%` }} /></div>
        </div>) : <p className="text-sm text-subtle">Selected after your question is understood</p> },
    { n: 4, title: "Intelligence", s: s4, from: s4, to: s4, body: s4 === "done"
        ? <p className="text-sm text-ink-2">Report ready · <span className="num">{duration(run.totalMs)}</span></p>
        : s4 === "active" ? <p className="text-sm text-muted">Putting the evidence together…</p> : <p className="text-sm text-subtle">Waiting for the agents</p> },
  ];

  return (
    <section aria-label="Analysis pipeline" aria-live="polite">
      <ol className="grid gap-5 md:grid-cols-4 md:gap-4">
        {items.map((it, i) => (
          <li key={it.n} className="relative flex gap-4 md:block">
            <div className="relative md:h-8">
              <StageDot n={it.n} s={it.s} />
              {i < items.length - 1 && <Connector from={it.from} to={items[i + 1].s} />}
            </div>
            <div className="min-w-0 pb-2 md:mt-4">
              <p className="eyebrow mb-1.5">{it.title}</p>
              {it.body}
            </div>
          </li>
        ))}
      </ol>

      {lanes.length > 0 && (
        <div className="mt-8 grid gap-6 lg:grid-cols-3">
          {lanes.map((l) => (
            <div key={l.id}>
              <div className="mb-3 flex items-baseline justify-between gap-3"><p className="text-sm font-medium text-ink">{l.title}</p><p className="truncate text-xs text-subtle">{l.blurb}</p></div>
              <ul className="space-y-3">{l.steps.map((st) => <AgentNode key={st.key} info={AGENTS[st.key]} st={st} />)}</ul>
            </div>
          ))}
        </div>
      )}

      {run.steps.length > 0 && notNeeded.length > 0 && (
        <p className="mt-6 text-xs leading-relaxed text-subtle">
          <span className="text-muted">Not needed for this question:</span> {notNeeded.map((k) => AGENTS[k].title).join(" · ")}
        </p>
      )}
      {live && run.phase === "understanding" && <div className="mt-6"><span className="flow-line block w-full" /></div>}
    </section>
  );
}

/** One-line recap used inside finished reports. */
export function PipelineStrip({ run }: { run: RunState }) {
  const total = run.totalMs;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
      <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-up" />Analysed in <span className="num text-ink-2">{duration(total)}</span></span>
      <span aria-hidden className="h-3 w-px bg-line" />
      <span>Understanding <span className="num text-ink-2">{duration(run.planMs)}</span></span>
      {run.steps.map((s) => (
        <span key={s.key} className={cn(s.status === "failed" && "text-down")}>{AGENTS[s.key].title} <span className="num text-ink-2">{duration(s.durationMs)}</span></span>
      ))}
    </div>
  );
}
