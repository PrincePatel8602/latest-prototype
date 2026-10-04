"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, RotateCw } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import PipelineView from "@/components/pipeline/PipelineView";
import Report from "@/components/report/Report";
import { Card, Container, ErrorState } from "@/components/ui/ui";
import { useAnalysis } from "@/hooks/useAnalysis";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { loadHistory, type HistoryEntry } from "@/lib/history";

export const EXAMPLES = [
  { q: "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?", tag: "Impact on you" },
  { q: "Explain why my portfolio risk increased.", tag: "Risk" },
  { q: "Show possible hedging strategies.", tag: "Hedging" },
  { q: "Which hurricanes formed in 2010, and how strong were they?", tag: "History" },
  { q: "Find historical storms similar to a Category 4 Gulf hurricane.", tag: "Analogues" },
  { q: "Which assets are most exposed?", tag: "Exposure" },
];

function Composer({ value, onChange, onSubmit, busy, compact }: { value: string; onChange: (v: string) => void; onSubmit: () => void; busy: boolean; compact?: boolean }) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (value.trim().length >= 3 && !busy) onSubmit(); }} role="search"
      className={cn("glass flex items-center gap-2 rounded-full p-1.5 pl-6 transition focus-within:border-accent/50", compact ? "" : "sm:p-2 sm:pl-7")}>
      <label htmlFor="q" className="sr-only">Your question</label>
      <input id="q" value={value} onChange={(e) => onChange(e.target.value)} maxLength={500} autoComplete="off" autoFocus={!compact} disabled={busy}
        placeholder="Ask about a storm, your risk, a hedge, or a year in history…"
        className={cn("min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-subtle disabled:opacity-60", compact ? "py-2.5 text-[15px]" : "py-3 text-base sm:text-lg")} />
      <button type="submit" disabled={busy || value.trim().length < 3} aria-label="Run analysis"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-ink text-bg transition hover:bg-white active:scale-95 disabled:opacity-30 sm:h-12 sm:w-12">
        <ArrowUp className="h-5 w-5" />
      </button>
    </form>
  );
}

function Inner() {
  const params = useSearchParams();
  const { state, run, reset } = useAnalysis();
  const [text, setText] = useState(params.get("q") ?? "");
  const [recent, setRecent] = useState<HistoryEntry[]>([]);
  const auto = useRef(false);
  const idle = state.phase === "idle";
  const busy = state.phase === "understanding" || state.phase === "running";

  useEffect(() => setRecent(loadHistory().slice(0, 3)), [state.phase]);
  useEffect(() => {
    const q = params.get("q");
    if (q && !auto.current) { auto.current = true; setText(q); run(q); }
  }, [params, run]);

  const go = (q: string) => { setText(q); run(q); };

  return (
    <Container className="pb-8 pt-12 sm:pt-20">
      <header className={cn("mx-auto text-center transition-all", idle ? "max-w-3xl" : "max-w-2xl")}>
        <p className="eyebrow mb-4">Ask FinSight</p>
        <h1 className={cn(idle ? "display text-balance" : "h1 text-balance")}><span className="text-fade">{idle ? "What would you like to understand?" : "Here’s what we’re finding"}</span></h1>
        {idle && <p className="lead mx-auto mt-5 max-w-xl">Ask in plain English. You’ll watch each step happen, then get the evidence behind the answer.</p>}
      </header>

      <div className={cn("mx-auto mt-9", idle ? "max-w-2xl" : "max-w-2xl")}><Composer value={text} onChange={setText} onSubmit={() => go(text.trim())} busy={busy} compact={!idle} /></div>

      <AnimatePresence mode="wait">
        {idle && (
          <motion.div key="idle" exit={{ opacity: 0, y: -8 }} className="mx-auto mt-10 max-w-2xl">
            <p className="eyebrow mb-3 text-center">Try one of these</p>
            <ul className="divide-y divide-line-soft overflow-hidden rounded-2xl border border-line-soft">
              {EXAMPLES.map((e) => (
                <li key={e.q}>
                  <button type="button" onClick={() => go(e.q)} className="group flex w-full items-center justify-between gap-4 px-5 py-3.5 text-left transition hover:bg-surface">
                    <span className="text-[15px] text-ink-2 group-hover:text-ink">{e.q}</span>
                    <span className="hidden shrink-0 text-xs text-subtle sm:block">{e.tag}</span>
                  </button>
                </li>
              ))}
            </ul>
            {recent.length > 0 && (
              <div className="mt-10">
                <div className="mb-3 flex items-baseline justify-between"><p className="eyebrow">Recent</p><Link href="/history" className="text-xs text-muted hover:text-ink">All history</Link></div>
                <ul className="space-y-2">{recent.map((h) => (
                  <li key={h.id}><Link href={`/history/${h.id}`} className="block rounded-2xl border border-line-soft px-5 py-3.5 transition hover:border-line hover:bg-surface">
                    <p className="line-clamp-1 text-sm text-ink-2">{h.query}</p><p className="mt-0.5 text-xs text-subtle">{h.headline} · {timeAgo(h.createdAt)}</p></Link></li>
                ))}</ul>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {!idle && (
        <div className="mx-auto mt-14 max-w-6xl">
          {state.phase === "error" ? (
            <Card><ErrorState title="The analysis didn’t complete" body={state.error} onRetry={() => run(state.query)} /></Card>
          ) : state.phase === "done" ? (
            <Report run={state} />
          ) : (
            <Card className="p-6 sm:p-10"><PipelineView run={state} live /></Card>
          )}
          {state.phase === "done" && (
            <div className="mt-12 flex justify-center">
              <button type="button" onClick={() => { reset(); setText(""); window.scrollTo({ top: 0, behavior: "smooth" }); }} className="inline-flex items-center gap-2 rounded-full border border-line px-5 py-2.5 text-sm text-muted transition hover:border-subtle hover:text-ink">
                <RotateCw className="h-3.5 w-3.5" /> Ask something else
              </button>
            </div>
          )}
        </div>
      )}
    </Container>
  );
}

export default function AskClient() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
