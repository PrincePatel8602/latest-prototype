"use client";

import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "motion/react";
import { useRef, useState, type ReactNode } from "react";
import { ICONS } from "@/components/pipeline/PipelineView";
import { Badge, Container, SectionHeading } from "@/components/ui/ui";
import DotPlot from "@/components/viz/DotPlot";
import { Reveal } from "@/components/ui/Reveal";
import { useParallaxStrength } from "@/hooks/useParallax";
import { AGENTS, DATA_SOURCES, LANES, STEP_ORDER, type StepKey } from "@/lib/agents";
import { cn } from "@/lib/cn";

export type StoryDot = { id: string; label: string; value: number; solid?: boolean };

const EXAMPLE = "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?";
// For that exact question the rule-based parser selects these agents (verified against the backend).
const EXAMPLE_PLAN: StepKey[] = ["weather", "news", "market", "historical", "exposure", "scenario", "risk", "fusion", "hedging"];

const STAGES = [
  { title: "You ask", body: "Plain English in. No forms, no filters, no jargon." },
  { title: "It understands", body: "An AI model reads the question and extracts what matters: the goal, the event, the place, the period, and whether it is about your holdings. If the model is unavailable, a rule-based parser takes over." },
  { title: "It chooses its agents", body: "Only the specialists the question needs are called. A question about 2010 never touches live feeds or your portfolio." },
  { title: "They gather data", body: "Live feeds for what is happening now, and decades of stored history for what happened before. Every source is named." },
  { title: "Python does the maths", body: "Volatility, exposure, event studies and hedge tests are calculated in code from real prices. The AI never does arithmetic." },
  { title: "Evidence is weighed", body: "What similar storms did to holdings like yours is measured, then graded for reliability. No hand-picked weights, and weak evidence is called weak." },
  { title: "You get a report", body: "The finding first, then the evidence, then the technical detail for anyone who wants to check the work." },
];

function Visual({ i, dots }: { i: number; dots: StoryDot[] | null }): ReactNode {
  switch (i) {
    case 0:
      return <div className="rounded-2xl border border-line bg-bg-elev p-5"><p className="eyebrow mb-2">Example question</p><p className="text-lg leading-snug text-ink">{EXAMPLE}<span className="ml-0.5 inline-block h-5 w-0.5 translate-y-1 bg-accent breathe" /></p></div>;
    case 1:
      return (
        <div className="rounded-2xl border border-line bg-bg-elev p-5"><p className="eyebrow mb-3">Understood as</p>
          <div className="flex flex-wrap gap-2">{[["Goal", "Impact of an event"], ["Event", "hurricane"], ["Strength", "Category 4"], ["Place", "Gulf of Mexico"], ["Scope", "Your portfolio"]].map(([k, v]) => <Badge key={k}><span className="text-subtle">{k}</span> {v}</Badge>)}</div>
        </div>);
    case 2:
      return (
        <div className="grid gap-3 sm:grid-cols-3">{LANES.map((l) => (
          <div key={l.id} className="rounded-2xl border border-line bg-bg-elev p-4"><p className="eyebrow mb-3">{l.title}</p>
            <ul className="space-y-1.5">{STEP_ORDER.filter((k) => AGENTS[k].lane === l.id).map((k) => {
              const on = EXAMPLE_PLAN.includes(k), Icon = ICONS[k];
              return <li key={k} className={cn("flex items-center gap-2 text-[13px]", on ? "text-ink" : "text-subtle line-through decoration-line")}><Icon className={cn("h-3.5 w-3.5", on ? "text-accent" : "text-subtle")} />{AGENTS[k].title}</li>;
            })}</ul></div>
        ))}</div>);
    case 3:
      return <div className="flex flex-wrap gap-2.5">{DATA_SOURCES.map((s) => (
        <div key={s.name} className="rounded-2xl border border-line bg-bg-elev px-4 py-3"><p className="text-sm font-medium text-ink">{s.name}</p><p className="mt-0.5 max-w-[15rem] text-xs leading-snug text-muted">{s.detail}</p></div>))}</div>;
    case 4:
      return <div className="grid gap-3 sm:grid-cols-3">{[["Exposure", "How concentrated you are, by sector"], ["Volatility", "How much your holdings swing, from real daily prices"], ["Event study", "What the market did around each past storm"]].map(([t, d]) => (
        <div key={t} className="rounded-2xl border border-line bg-bg-elev p-4"><p className="text-sm font-medium text-ink">{t}</p><p className="mt-1 text-xs leading-relaxed text-muted">{d}</p><p className="num mt-4 text-xs text-accent">computed in Python</p></div>))}</div>;
    case 5:
      return (
        <div className="rounded-2xl border border-line bg-bg-elev p-5"><p className="eyebrow mb-3">Past storms, one dot each</p>
          {dots?.length ? <DotPlot dots={dots} ariaLabel="Past storms and how far the portfolio moved after each" /> : <p className="py-6 text-sm text-muted">Connect the FinSight API to see the real storms here.</p>}</div>);
    default:
      return <div className="space-y-2.5 rounded-2xl border border-line bg-bg-elev p-5">{[["Executive insight", "w-3/4"], ["Supporting evidence", "w-full"], ["Risk and drivers", "w-5/6"], ["Technical details", "w-2/3"]].map(([t, w], n) => (
        <div key={t}><p className="mb-1.5 text-xs text-muted">{n + 1}. {t}</p><div className={cn("h-2 rounded-full", n === 0 ? "bg-accent/70" : "bg-line", w)} /></div>))}</div>;
  }
}

export default function PipelineStory({ dots }: { dots: StoryDot[] | null }) {
  const k = useParallaxStrength();
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  useMotionValueEvent(scrollYProgress, "change", (v) => setActive(Math.max(0, Math.min(STAGES.length - 1, Math.floor(v * STAGES.length * 0.999)))));
  const header = <SectionHeading eyebrow="The intelligence pipeline" title="From a question to evidence, one visible step at a time." lead="This is the real architecture of the system. In the app, each step lights up as it truly happens." />;

  // Phones, tablets and reduced-motion visitors get a plain, fast vertical story.
  // One wrapper element for every layout: useScroll must keep observing the same node when the layout switches.
  if (!k) {
    return (
      <div ref={ref}><Container className="py-24">
        {header}
        <ol className="mt-12 space-y-12">{STAGES.map((s, i) => (
          <Reveal as="li" key={s.title}><p className="eyebrow mb-2">Step {i + 1}</p><h3 className="h2 !text-2xl">{s.title}</h3><p className="mt-2 max-w-xl text-[15px] leading-relaxed text-muted">{s.body}</p><div className="mt-5"><Visual i={i} dots={dots} /></div></Reveal>
        ))}</ol>
      </Container></div>
    );
  }

  return (
    <div ref={ref} style={{ height: `${STAGES.length * 62}vh` }} className="relative">
      <div className="sticky top-14 flex h-[calc(100vh-3.5rem)] items-center">
        <Container wide className="grid items-center gap-16 lg:grid-cols-[minmax(0,26rem)_1fr]">
          <div>
            {header}
            <ol className="mt-10 space-y-1">{STAGES.map((s, i) => (
              <li key={s.title} className="flex items-center gap-4">
                <span className={cn("num w-5 text-xs transition-colors duration-500", i === active ? "text-accent" : "text-subtle")}>{String(i + 1).padStart(2, "0")}</span>
                <span className={cn("h-px transition-all duration-500", i === active ? "w-10 bg-accent" : "w-4 bg-line")} />
                <span className={cn("py-1.5 text-[15px] transition-colors duration-500", i === active ? "font-medium text-ink" : "text-subtle")}>{s.title}</span>
              </li>
            ))}</ol>
          </div>
          <div className="relative min-h-[26rem]">
            <AnimatePresence mode="wait">
              <motion.div key={active} initial={{ opacity: 0, y: 18, filter: "blur(6px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} exit={{ opacity: 0, y: -12, filter: "blur(4px)" }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
                <div className="glass rounded-[28px] p-7 sm:p-9">
                  <p className="eyebrow">Step {active + 1} of {STAGES.length}</p>
                  <h3 className="h1 mt-3 !text-[2.1rem]">{STAGES[active].title}</h3>
                  <p className="lead mt-3 max-w-xl !text-[1.05rem]">{STAGES[active].body}</p>
                  <div className="mt-7"><Visual i={active} dots={dots} /></div>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </Container>
      </div>
    </div>
  );
}
