"use client";

import { motion, useScroll, useTransform, useSpring } from "motion/react";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiState } from "@/hooks/useApi";
import { useParallaxStrength } from "@/hooks/useParallax";
import type { DashboardSummary, HistoricalStatus, WeatherResponse } from "@/types/api";
import { gradeLabel } from "@/lib/insight";
import { signedPct } from "@/lib/format";
import { cn } from "@/lib/cn";
import Live from "@/components/ui/Live";
import { Badge, Button, Container, Skeleton } from "@/components/ui/ui";
import DotPlot from "@/components/viz/DotPlot";

function Chip({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("glass rounded-2xl px-4 py-3", className)}>
      <p className="eyebrow !text-[0.65rem]">{label}</p>
      <div className="mt-1.5 text-sm text-ink">{children}</div>
    </div>
  );
}

export default function Hero({ summary, weather, status, onRetry }: { summary: ApiState<DashboardSummary>; weather: ApiState<WeatherResponse>; status: ApiState<HistoricalStatus>; onRetry: () => void }) {
  const k = useParallaxStrength();
  const { scrollY } = useScroll();
  
  // Smooth the scroll value for an Apple-style buttery parallax
  const smoothY = useSpring(scrollY, { stiffness: 60, damping: 20, restDelta: 0.001 });

  // Background -> very slow
  const orbA = useTransform(smoothY, [0, 1000], [0, -30 * k]);
  const orbB = useTransform(smoothY, [0, 1000], [0, -50 * k]);
  
  // Hero text -> slow
  const textY = useTransform(smoothY, [0, 800], [0, -70 * k]);
  const textOpacity = useTransform(smoothY, [0, 560], [1, k ? 0.2 : 1]);
  const textScale = useTransform(smoothY, [0, 800], [1, k ? 0.98 : 1]);
  
  // Main AI visualization -> medium
  const cardY = useTransform(smoothY, [0, 1000], [0, -140 * k]);
  
  // Floating charts/data -> slightly faster
  const chipA = useTransform(smoothY, [0, 1000], [0, -200 * k]);
  const chipB = useTransform(smoothY, [0, 1000], [0, -230 * k]);
  const chipC = useTransform(smoothY, [0, 1000], [0, -260 * k]);

  const s = summary.status === "success" ? summary.data : null;
  const w = weather.status === "success" ? weather.data : null;
  const h = status.status === "success" ? status.data : null;

  return (
    <section className="relative isolate overflow-hidden pb-24 sm:pb-32">
      <div aria-hidden className="grid-fade absolute inset-0 -z-10" />
      <motion.div aria-hidden style={{ y: orbA }} className="orb -top-48 left-1/2 -z-10 h-[520px] w-[860px] -translate-x-1/2 bg-accent/[0.16]" />
      <motion.div aria-hidden style={{ y: orbB }} className="orb -right-40 top-[38%] -z-10 h-[420px] w-[420px] bg-accent/[0.07]" />

      <Container wide className="pt-16 sm:pt-24">
        <motion.div style={{ y: textY, opacity: textOpacity, scale: textScale }} className="mx-auto max-w-4xl text-center will-change-transform">
          <motion.p initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}
            className="mx-auto mb-7 inline-flex items-center gap-2 rounded-full border border-line bg-surface/60 px-3.5 py-1.5 text-xs text-muted">
            <span className={cn("h-1.5 w-1.5 rounded-full", s ? "bg-up" : "bg-subtle")} />
            {s ? "Connected to live data and 40 years of history" : "Financial intelligence that shows its work"}
          </motion.p>
          <motion.h1 initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.05, ease: [0.16, 1, 0.3, 1] }} className="display text-balance">
            <span className="text-fade">Intelligence you can</span> <span className="text-accent-fade">watch think.</span>
          </motion.h1>
          <motion.p initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.18, ease: [0.16, 1, 0.3, 1] }} className="lead mx-auto mt-7 max-w-2xl text-balance">
            Ask about a storm, a market or your own portfolio. AEGIS shows every step it takes, every source it reads, and the evidence behind every number.
          </motion.p>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }} className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button href="/ask" size="lg">Ask a question <ArrowRight className="h-4 w-4" /></Button>
          </motion.div>
        </motion.div>

        <div className="relative mx-auto mt-16 max-w-4xl sm:mt-24">
          <motion.div style={{ y: cardY }} initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1 }} transition={{ duration: 1, delay: 0.4, ease: [0.16, 1, 0.3, 1] }} className="will-change-transform">
            <div className="glass rounded-[28px] p-5 sm:p-8">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="eyebrow">A real analysis, live</p>
                  <p className="mt-2 text-lg font-medium leading-snug tracking-tight text-ink sm:text-xl">A Category 4 hurricane in the Gulf of Mexico, and your portfolio</p>
                </div>
                {s?.hurricane_impact.status === "ok" && <Badge tone="accent">{s.hurricane_impact.n_storms} real past storms</Badge>}
              </div>
              <div className="mt-6">
                <Live state={summary} onRetry={onRetry} quiet skeleton={<div className="space-y-4"><Skeleton className="h-28 w-full" /><div className="grid grid-cols-3 gap-4"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div></div>}>
                  {(d) => d.hurricane_impact.status === "ok" && d.hurricane_impact.storms?.length ? (
                    <>
                      <DotPlot ariaLabel="Past hurricanes and how far a portfolio of oil and gas holdings moved after each" median={d.hurricane_impact.median_pct} p10={d.hurricane_impact.p10_pct} p90={d.hurricane_impact.p90_pct}
                        dots={d.hurricane_impact.storms.map((x) => ({ id: x.storm_id, label: x.label, value: x.value_pct, solid: x.independent }))} />
                      <dl className="mt-6 grid grid-cols-3 gap-4 border-t border-line-soft pt-5">
                        <div><dt className="eyebrow !text-[0.65rem]">Median, 5 days</dt><dd className="num mt-1.5 text-xl text-ink sm:text-2xl">{signedPct(d.hurricane_impact.median_pct, 2)}</dd></div>
                        <div><dt className="eyebrow !text-[0.65rem]">Typical range</dt><dd className="num mt-1.5 text-xl text-ink sm:text-2xl">{signedPct(d.hurricane_impact.p10_pct)} <span className="text-subtle">to</span> {signedPct(d.hurricane_impact.p90_pct)}</dd></div>
                        <div><dt className="eyebrow !text-[0.65rem]">Evidence</dt><dd className="mt-1.5 text-base font-medium text-ink sm:text-lg">{gradeLabel(d.hurricane_impact.grade ?? "")}</dd></div>
                      </dl>
                    </>
                  ) : <p className="py-8 text-center text-sm text-muted">The reference analysis needs the stored storm and price history.</p>}
                </Live>
              </div>
            </div>
          </motion.div>

          <div className="mt-5 grid gap-3 sm:grid-cols-3 min-[1360px]:mt-0 min-[1360px]:block">
            <motion.div style={{ y: chipA }} className="min-[1360px]:absolute min-[1360px]:right-full min-[1360px]:top-10 min-[1360px]:mr-6">
              <Chip label="Portfolio risk" className="min-[1360px]:w-48">
                {s?.risk.status === "ok" ? <><span className="num text-lg">{s.risk.recent_vol_pct!.toFixed(1)}%</span> <span className="text-xs text-muted">20-day volatility, {s.risk.classification}</span></> : <Skeleton className="h-6 w-24" />}
              </Chip>
            </motion.div>
            <motion.div style={{ y: chipB }} className="min-[1360px]:absolute min-[1360px]:left-full min-[1360px]:top-24 min-[1360px]:ml-6">
              <Chip label="Right now" className="min-[1360px]:w-48">
                {w ? <><span className="num text-lg">{w.events.length}</span> <span className="text-xs text-muted">active tropical system{w.events.length === 1 ? "" : "s"}{w.events[0] ? `, incl. ${w.events[0].name.replace(/^Hurricane |^Tropical Storm /, "")}` : ""}</span></> : <Skeleton className="h-6 w-24" />}
              </Chip>
            </motion.div>
            <motion.div style={{ y: chipC }} className="min-[1360px]:absolute min-[1360px]:bottom-6 min-[1360px]:right-full min-[1360px]:mr-6">
              <Chip label="The record" className="min-[1360px]:w-48">
                {h ? <><span className="num text-lg">{h.storms.toLocaleString()}</span> <span className="text-xs text-muted">Atlantic storms since 1980</span></> : <Skeleton className="h-6 w-24" />}
              </Chip>
            </motion.div>
          </div>
        </div>
      </Container>
    </section>
  );
}
