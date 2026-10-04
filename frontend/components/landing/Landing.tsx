"use client";

import { ArrowRight, ArrowUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Hero from "@/components/landing/Hero";
import IntelligencePipeline from "@/components/pipeline/IntelligencePipeline";
import { ICONS } from "@/components/pipeline/PipelineView";
import { Reveal } from "@/components/ui/Reveal";
import Live from "@/components/ui/Live";
import { Badge, Button, Card, Container, SectionHeading, Skeleton } from "@/components/ui/ui";
import DotPlot from "@/components/viz/DotPlot";
import LineChart from "@/components/viz/LineChart";
import { HBars, PercentileTrack } from "@/components/viz/small";
import { useApi } from "@/hooks/useApi";
import { getDashboardSummary, getHistoricalStatus, getRiskDrivers, getWeather } from "@/lib/api";
import type { ApiState } from "@/hooks/useApi";
import type { DashboardSummary } from "@/types/api";
import type { RiskDrivers } from "@/types/agents";
import { AGENTS, LANES, STEP_ORDER } from "@/lib/agents";
import { pct, signedPct } from "@/lib/format";
import { gradeLabel } from "@/lib/insight";

const EXAMPLES = [
  "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?",
  "Explain why my portfolio risk increased.",
  "Which hurricanes formed in 2010, and how strong were they?",
];

function AskBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const go = (text: string) => text.trim().length >= 3 && router.push(`/ask?q=${encodeURIComponent(text.trim())}`);
  return (
    <div className="w-full max-w-xl">
      <form onSubmit={(e) => { e.preventDefault(); go(q); }} className="glass flex items-center gap-2 rounded-full p-1.5 pl-5 focus-within:border-accent/50">
        <label htmlFor="home-q" className="sr-only">Your question</label>
        <input id="home-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything about a storm or your risk…" className="min-w-0 flex-1 bg-transparent py-2.5 text-[15px] text-ink outline-none placeholder:text-subtle" />
        <button type="submit" aria-label="Run analysis" disabled={q.trim().length < 3} className="grid h-10 w-10 place-items-center rounded-full bg-ink text-bg transition hover:bg-white active:scale-95 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
      </form>
      <ul className="mt-4 space-y-1.5">{EXAMPLES.map((e) => (
        <li key={e}><button type="button" onClick={() => go(e)} className="group flex items-start gap-2 text-left text-[13px] leading-snug text-muted transition hover:text-ink"><ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle transition group-hover:translate-x-0.5 group-hover:text-accent" />{e}</button></li>
      ))}</ul>
    </div>
  );
}

function Agents() {
  return (
    <Container wide className="py-24 sm:py-32">
      <SectionHeading eyebrow="The specialists" title="Ten agents, each with one clear job." lead="A question only calls the ones it needs. Each names its sources, and each can fail without taking the others down." />
      <div className="mt-14 grid gap-10 lg:grid-cols-3">
        {LANES.map((l, li) => (
          <Reveal key={l.id} delay={li * 0.08}>
            <div className="mb-4 flex items-baseline gap-3"><h3 className="h3">{l.title}</h3><p className="text-xs text-subtle">{l.blurb}</p></div>
            <ul className="space-y-3">{STEP_ORDER.filter((k) => AGENTS[k].lane === l.id).map((k) => {
              const a = AGENTS[k], Icon = ICONS[k];
              return (
                <li key={k} className="surface-flat p-4 transition hover:border-line">
                  <div className="flex items-start gap-3">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-line text-accent"><Icon className="h-[18px] w-[18px]" /></span>
                    <div className="min-w-0"><p className="text-sm font-medium text-ink">{a.title}</p><p className="mt-1 text-[13px] leading-snug text-muted">{a.does}</p>
                      <p className="mt-2.5 flex flex-wrap gap-1.5">{a.sources.map((s) => <Badge key={s}>{s}</Badge>)}</p></div>
                  </div>
                </li>);
            })}</ul>
          </Reveal>
        ))}
      </div>
    </Container>
  );
}

function EvidenceStory({ summary, onRetry }: { summary: ApiState<DashboardSummary>; onRetry: () => void }) {
  return (
    <Container wide className="py-24 sm:py-32">
      <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,24rem)_1fr] lg:gap-20">
        <Reveal>
          <SectionHeading eyebrow="The analysis" title="Every dot is a storm that really happened." lead="When a Category 4 hurricane enters the Gulf, what has the market done to holdings like yours in the five days after? FinSight measures it storm by storm, instead of guessing." />
          <Live state={summary} quiet>{(d) => d.hurricane_impact.status === "ok" ? (
            <p className="mt-6 text-[15px] leading-relaxed text-ink-2">The result: a median move of <span className="num text-ink">{signedPct(d.hurricane_impact.median_pct, 2)}</span>, with the middle 80% of storms between <span className="num text-ink">{signedPct(d.hurricane_impact.p10_pct)}</span> and <span className="num text-ink">{signedPct(d.hurricane_impact.p90_pct)}</span>. Evidence grade: <span className="text-ink">{gradeLabel(d.hurricane_impact.grade ?? "")}</span>. FinSight says so plainly rather than inventing a signal.</p>
          ) : null}</Live>
        </Reveal>
        <Reveal delay={0.1}>
          <Card className="p-5 sm:p-8">
            <Live state={summary} onRetry={onRetry} quiet skeleton={<Skeleton className="h-44 w-full" />}>{(d) => d.hurricane_impact.status === "ok" && d.hurricane_impact.storms?.length ? (
              <>
                <DotPlot ariaLabel="Past hurricanes and how far the portfolio moved after each" median={d.hurricane_impact.median_pct} p10={d.hurricane_impact.p10_pct} p90={d.hurricane_impact.p90_pct}
                  dots={d.hurricane_impact.storms.map((x) => ({ id: x.storm_id, label: x.label, value: x.value_pct, solid: x.independent }))} />
                <p className="mt-5 text-xs leading-relaxed text-muted">Hover a dot to see the storm. Green: the portfolio rose. Red: it fell. The shaded band holds the middle 80% of outcomes.</p>
              </>) : <p className="py-10 text-center text-sm text-muted">Needs the stored storm and price history.</p>}</Live>
          </Card>
        </Reveal>
      </div>
    </Container>
  );
}

function RiskStory({ drivers, onRetry }: { drivers: ApiState<RiskDrivers>; onRetry: () => void }) {
  return (
    <Container wide className="py-24 sm:py-32">
      <div className="grid items-center gap-12 lg:grid-cols-[1fr_minmax(0,24rem)] lg:gap-20">
        <Reveal className="order-2 lg:order-1">
          <Card className="p-5 sm:p-8">
            <Live state={drivers} onRetry={onRetry} quiet skeleton={<Skeleton className="h-64 w-full" />}>{(d) => d.status === "ok" && d.risk_change ? (
              <>
                <p className="h3">How much your holdings swing, over the last year</p>
                <div className="mt-4"><LineChart ariaLabel="Annualised 20-day volatility over the last year" area height={220} yFormat={(v) => `${v.toFixed(0)}%`} refLines={[{ y: d.risk_change.year_vol_pct, label: "1-year average" }]}
                  series={[{ id: "v", label: "Volatility", color: "var(--color-accent)", points: d.rolling_volatility.map((p) => ({ x: new Date(p.date).getTime(), y: p.vol_pct })) }]} /></div>
                <div className="mt-6 grid gap-6 border-t border-line-soft pt-6 sm:grid-cols-2">
                  <PercentileTrack percentile={d.risk_change.history_percentile} label="Recent volatility" />
                  <HBars format={(v) => `${v.toFixed(0)}%`} max={100} rows={d.holdings.map((h) => ({ label: h.symbol, sub: "share of risk", value: h.risk_share_recent_pct }))} />
                </div>
              </>) : <p className="py-10 text-center text-sm text-muted">Needs the stored price history.</p>}</Live>
          </Card>
        </Reveal>
        <Reveal className="order-1 lg:order-2">
          <SectionHeading eyebrow="Risk and drivers" title="Did your risk really change, or does it just feel that way?" lead="FinSight compares today’s volatility with its own past, then names the holding behind it. It answers from real prices, and says so when nothing unusual is happening." />
          <Live state={drivers} quiet>{(d) => d.status === "ok" && d.risk_change ? (
            <p className="mt-6 text-[15px] leading-relaxed text-ink-2">Right now: <span className="num text-ink">{pct(d.risk_change.recent_vol_pct)}</span> against <span className="num text-ink">{pct(d.risk_change.year_vol_pct)}</span> over the past year, which is {d.risk_change.classification === "typical" ? "inside the normal range" : d.risk_change.classification}.</p>
          ) : null}</Live>
        </Reveal>
      </div>
    </Container>
  );
}

const PROMISES = [
  ["Visible", "Every step the system takes appears as it happens, with the time each one really took."],
  ["Graded", "Evidence is rated by sample size and statistics, not by confidence theatre. Weak evidence is labelled weak."],
  ["Honest", "Live or demo data is labelled. Assumptions are labelled. What is not modeled is listed."],
];

export default function Landing() {
  const summary = useApi(getDashboardSummary);
  const drivers = useApi(getRiskDrivers);
  const weather = useApi(getWeather);
  const status = useApi(getHistoricalStatus);
  const dots = summary.state.status === "success" && summary.state.data.hurricane_impact.storms
    ? summary.state.data.hurricane_impact.storms.map((x) => ({ id: x.storm_id, label: x.label, value: x.value_pct, solid: x.independent })) : null;
  return (
    <>
      <Hero summary={summary.state} weather={weather.state} status={status.state} onRetry={summary.reload} />

      <Container className="py-24 sm:py-36">
        <IntelligencePipeline />
      </Container>
      <Agents />
      <EvidenceStory summary={summary.state} onRetry={summary.reload} />
      <RiskStory drivers={drivers.state} onRetry={drivers.reload} />

      <Container className="py-24 sm:py-36">
        <Reveal className="mx-auto max-w-3xl text-center">
          <p className="eyebrow mb-5">Why it matters</p>
          <h2 className="display text-balance"><span className="text-fade">Trust the answer because you can check it.</span></h2>
          <p className="lead mx-auto mt-6 max-w-xl">Financial AI is only useful if you can see why it says what it says.</p>
          <div className="mt-10 flex flex-wrap justify-center gap-3"><Button href="/ask" size="lg">Ask your first question <ArrowRight className="h-4 w-4" /></Button><Button href="/about" variant="ghost" size="lg">How to read the evidence</Button></div>
        </Reveal>
        <div className="mx-auto mt-20 grid max-w-5xl gap-8 border-t border-line-soft pt-10 md:grid-cols-3">
          {PROMISES.map(([t, d], i) => <Reveal key={t} delay={i * 0.08}><p className="h3">{t}</p><p className="mt-2 text-sm leading-relaxed text-muted">{d}</p></Reveal>)}
        </div>
      </Container>
    </>
  );
}
