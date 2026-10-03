"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { Reveal } from "@/components/ui/Reveal";
import Live from "@/components/ui/Live";
import { Badge, Card, Container, Skeleton, Stat } from "@/components/ui/ui";
import LineChart from "@/components/viz/LineChart";
import { HBars, PercentileTrack } from "@/components/viz/small";
import { useApi } from "@/hooks/useApi";
import { getPortfolio, getPrices, getRiskDrivers } from "@/lib/api";
import { pct, signedPct, usd } from "@/lib/format";

// useApi needs a STABLE function: an inline arrow would change every render and re-fetch forever.
const getHoldingPrices = () => getPrices("XOM,CVX,UNG", 252);
const COLORS = ["#6ea8ff", "#4ade9b", "#f5c45e", "#c4a7ff", "#ff9d6e"];
const ASK = [
  ["Explain why my portfolio risk increased.", "Has my risk really changed?"],
  ["Show possible hedging strategies.", "What would have protected me?"],
  ["How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?", "What if a major storm hits?"],
];

export default function PortfolioClient() {
  const pf = useApi(getPortfolio);
  const drivers = useApi(getRiskDrivers);
  const prices = useApi(getHoldingPrices);
  return (
    <Container wide className="pb-8 pt-16 sm:pt-24">
      <Reveal className="max-w-3xl">
        <p className="eyebrow mb-4">Portfolio</p>
        <h1 className="display text-balance"><span className="text-fade">What you hold, and what drives it.</span></h1>
      </Reveal>

      <Live state={pf.state} onRetry={pf.reload} skeleton={<Skeleton className="mt-12 h-48 w-full" />}>
        {(p) => (
          <>
            <Reveal className="mt-12">
              <Card className="p-6 sm:p-9">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div><p className="eyebrow">{p.name}</p><p className="num mt-3 text-4xl font-medium text-ink sm:text-5xl">{usd(p.total_value)}</p></div>
                  <Badge tone={p.meta.source === "user" ? "accent" : "warn"}>{p.meta.source === "user" ? "Your portfolio" : "Demo portfolio, held in memory"}</Badge>
                </div>
                <div className="mt-8 grid gap-8 border-t border-line-soft pt-8 lg:grid-cols-[1.2fr_1fr]">
                  <div>
                    <p className="mb-4 text-[13px] text-muted">Holdings, by weight</p>
                    <div className="flex h-3 overflow-hidden rounded-full bg-line-soft" role="img" aria-label="Portfolio weights">
                      {p.holdings.map((h, i) => <div key={h.symbol} title={`${h.symbol} ${h.weight_pct}%`} style={{ width: `${h.weight_pct}%`, background: COLORS[i % COLORS.length] }} className="h-full border-r border-bg last:border-0" />)}
                    </div>
                    <ul className="mt-6 divide-y divide-line-soft">{p.holdings.map((h, i) => (
                      <li key={h.symbol} className="flex items-center gap-4 py-3.5">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                        <div className="min-w-0 flex-1"><p className="text-sm font-medium text-ink">{h.name} <span className="text-subtle">{h.symbol}</span></p><p className="text-xs text-muted">{h.sector}</p></div>
                        <div className="text-right"><p className="num text-sm text-ink">{h.weight_pct}%</p><p className="num text-xs text-muted">{usd(h.value_usd)}</p></div>
                      </li>))}</ul>
                  </div>
                  <div>
                    <p className="mb-4 text-[13px] text-muted">By sector</p>
                    <HBars rows={p.sector_exposure.map((s) => ({ label: s.sector, value: s.weight_pct, tone: s.sector === "Energy" ? ("warn" as const) : ("muted" as const) }))} max={100} />
                    <p className="mt-6 rounded-xl border border-line-soft bg-bg-elev px-4 py-3 text-[13px] leading-relaxed text-muted">{p.energy_exposure_pct}% of this portfolio is in energy, so hurricanes, oil and gas prices matter more to it than to most.</p>
                  </div>
                </div>
              </Card>
            </Reveal>

            <Reveal className="mt-4">
              <Card className="p-6 sm:p-9">
                <p className="h3">The last year, side by side</p>
                <p className="mt-1 text-[13px] text-muted">Each line starts at 100, so you can compare how holdings moved relative to each other. Real stored prices.</p>
                <div className="mt-5">
                  <Live state={prices.state} onRetry={prices.reload} quiet skeleton={<Skeleton className="h-64 w-full" />}>{(d) => d.series.length ? (
                    <>
                      <LineChart ariaLabel="Holdings rebased to 100 over the last year" height={260} yFormat={(v) => v.toFixed(0)} refLines={[{ y: 100, label: "start" }]}
                        series={d.series.map((s, i) => ({ id: s.symbol, label: s.symbol, color: COLORS[i % COLORS.length], points: s.points.map(([t, v]) => ({ x: new Date(t).getTime(), y: v })) }))} />
                      <ul className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-xs text-muted">{d.series.map((s, i) => <li key={s.symbol}><span style={{ color: COLORS[i % COLORS.length] }}>{s.symbol}</span> <span className="num text-ink-2">{signedPct(s.change_pct)}</span> over the period</li>)}</ul>
                    </>) : <p className="py-8 text-center text-sm text-muted">No stored price history for these holdings yet.</p>}</Live>
                </div>
              </Card>
            </Reveal>
          </>
        )}
      </Live>

      <Reveal className="mt-4">
        <Card className="p-6 sm:p-9">
          <Live state={drivers.state} onRetry={drivers.reload} quiet skeleton={<Skeleton className="h-56 w-full" />}>{(d) => d.status === "ok" && d.risk_change ? (
            <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr]">
              <div>
                <p className="h3">Has your risk changed?</p>
                <p className="mt-1 text-[13px] text-muted">How much your holdings swing day to day, over the last year. Today: <span className="num text-ink">{pct(d.risk_change.recent_vol_pct)}</span> against an average of <span className="num text-ink">{pct(d.risk_change.year_vol_pct)}</span>.</p>
                <div className="mt-4"><LineChart ariaLabel="Annualised 20-day volatility over the last year" area height={220} yFormat={(v) => `${v.toFixed(0)}%`} refLines={[{ y: d.risk_change.year_vol_pct, label: "1-year average" }]}
                  series={[{ id: "v", label: "Volatility", color: "#6ea8ff", points: d.rolling_volatility.map((x) => ({ x: new Date(x.date).getTime(), y: x.vol_pct })) }]} /></div>
              </div>
              <div className="space-y-8">
                <div><p className="mb-4 text-[13px] text-muted">Today against the last {Math.round(d.risk_change.history_days / 21)} months</p><PercentileTrack percentile={d.risk_change.history_percentile} label="Recent volatility" /></div>
                <div><p className="mb-4 text-[13px] text-muted">Which holding drives it</p><HBars format={(v) => `${v.toFixed(0)}%`} max={100} rows={d.holdings.map((h) => ({ label: h.symbol, sub: `${h.weight_pct.toFixed(0)}% weight`, value: h.risk_share_recent_pct, ghost: h.risk_share_year_pct }))} /></div>
              </div>
            </div>) : <p className="py-8 text-center text-sm text-muted">Risk drivers need the stored price history.</p>}</Live>
        </Card>
      </Reveal>

      <Reveal className="mt-16">
        <p className="eyebrow mb-4">Ask about it</p>
        <div className="grid gap-3 md:grid-cols-3">{ASK.map(([q, label]) => (
          <Link key={q} href={`/ask?q=${encodeURIComponent(q)}`} className="group surface-flat flex flex-col justify-between gap-6 p-5 transition hover:border-line">
            <p className="text-[15px] font-medium leading-snug text-ink">{label}</p>
            <p className="flex items-end justify-between gap-3 text-xs leading-snug text-muted"><span className="line-clamp-2">{q}</span><ArrowRight className="h-4 w-4 shrink-0 text-subtle transition group-hover:translate-x-0.5 group-hover:text-accent" /></p>
          </Link>))}</div>
      </Reveal>
    </Container>
  );
}
