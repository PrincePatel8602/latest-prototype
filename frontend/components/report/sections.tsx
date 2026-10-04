"use client";

import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Reveal } from "@/components/ui/Reveal";
import { Badge, Card, Disclosure, Kv, Stat } from "@/components/ui/ui";
import DotPlot from "@/components/viz/DotPlot";
import LineChart from "@/components/viz/LineChart";
import StormTimeline from "@/components/viz/StormTimeline";
import { HBars, PercentileTrack, RangeRow, ToneTrack } from "@/components/viz/small";
import { cn } from "@/lib/cn";
import { pct, signedPct, timeAgo, titleCase, usdSigned } from "@/lib/format";
import { SERIES_SHORT, categoryShort } from "@/lib/labels";
import { gradeLabel, type Insight } from "@/lib/insight";
import type { QueryPipelineResponse } from "@/types/agents";

export function Section({ eyebrow, title, lead, children, id }: { eyebrow: string; title: string; lead?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <Reveal as="section" className="mt-16 scroll-mt-24">
      <header className="mb-6 max-w-2xl" id={id}>
        <p className="eyebrow mb-2">{eyebrow}</p>
        <h2 className="h2">{title}</h2>
        {lead && <p className="mt-2 text-[15px] leading-relaxed text-muted">{lead}</p>}
      </header>
      {children}
    </Reveal>
  );
}

const TONE: Record<Insight["tone"], { label: string; tone: "up" | "warn" | "down" | "accent"; bar: string }> = {
  calm: { label: "Steady", tone: "up", bar: "from-up/70" },
  watch: { label: "Worth watching", tone: "warn", bar: "from-warn/70" },
  alert: { label: "Needs attention", tone: "down", bar: "from-down/70" },
  info: { label: "Insight", tone: "accent", bar: "from-accent/70" },
};

// --------------------------------------------------------------------------- 1. executive insight
export function ExecutiveInsight({ r, insight }: { r: QueryPipelineResponse; insight: Insight }) {
  const t = TONE[insight.tone];
  const parts: [string, string | undefined][] = [
    ["Weather", r.weather?.meta?.source], ["News", r.news?.meta?.source], ["Markets", r.market?.meta?.source], ["History", r.historical?.meta.source],
    ["Fusion", r.fusion?.meta.source], ["Risk", r.risk?.meta.source], ["Drivers", r.drivers?.meta.source], ["Hedging", r.hedging?.meta.source],
  ];
  const shown = parts.filter(([, s]) => s) as [string, string][];
  return (
    <Card className="relative overflow-hidden p-6 sm:p-10">
      <div aria-hidden className={cn("absolute inset-x-0 top-0 h-px bg-gradient-to-r to-transparent", t.bar)} />
      <div aria-hidden className="orb -right-24 -top-32 h-72 w-72 bg-accent/10" />
      <div className="relative">
        <div className="flex flex-wrap items-center gap-2"><p className="eyebrow">Executive insight</p><Badge tone={t.tone}>{t.label}</Badge></div>
        <h1 className="h1 mt-4 max-w-3xl text-balance text-ink">{insight.headline}</h1>
        <p className="lead mt-4 max-w-3xl text-ink-2/90">{insight.statement}</p>
        {insight.metrics.length > 0 && (
          <dl className="mt-9 grid grid-cols-2 gap-x-6 gap-y-7 border-t border-line-soft pt-8 lg:grid-cols-4">
            {insight.metrics.map((m) => <Stat key={m.label} label={m.label} value={m.value} hint={m.hint} />)}
          </dl>
        )}
        {shown.length > 0 && (
          <p className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted">
            <span className="text-subtle">Data used</span>
            {shown.map(([l, s]) => <span key={l} className="flex items-center gap-1.5"><span className={cn("h-1.5 w-1.5 rounded-full", s === "live" ? "bg-up" : "bg-warn")} />{l} <span className="text-subtle">{s === "live" ? "live" : "demo"}</span></span>)}
          </p>
        )}
      </div>
    </Card>
  );
}

// --------------------------------------------------------------------------- 2. supporting evidence
export function FusionEvidence({ r }: { r: QueryPipelineResponse }) {
  const f = r.fusion, p = f?.portfolio;
  const covered = useMemo(() => (f?.assets ?? []).filter((x) => x.covered && x.stats), [f]);
  const dom = useMemo<[number, number]>(() => {
    const v = covered.flatMap((c) => [c.stats!.p10 ?? 0, c.stats!.p90 ?? 0, c.scenario_shock_pct ?? 0, 0]);
    const m = Math.max(1, ...v.map(Math.abs));
    return [-m * 1.08, m * 1.08];
  }, [covered]);
  if (!f || f.status !== "ok" || !p) return null;
  const a = p.all_analogs;
  return (
    <Section eyebrow="Supporting evidence" title="What similar storms did to your portfolio"
      lead={<>Each dot is one real past storm: how much holdings like yours moved in the five days after it entered the Gulf, measured against the wider market. {a.grade === "not_distinguishable_from_zero" && "The dots scatter on both sides of zero, which is why the effect can't be told apart from chance."}</>}>
      <Card className="p-5 sm:p-8">
        <DotPlot ariaLabel={`${a.n} past storms and how far your portfolio moved after each`} median={a.median} p10={a.p10} p90={a.p90} marker={p.scenario_change_pct}
          markerLabel="Stress test" dots={p.per_storm.map((s) => ({ id: s.storm_id, label: s.label, value: s.value_pct, solid: s.independent }))} />
        <ul className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted">
          <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-up" /><span className="h-2.5 w-2.5 rounded-full bg-down" />A past storm (green = portfolio rose, red = fell)</li>
          <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border border-subtle" />Hollow = another Gulf storm was close, so not fully independent</li>
          <li className="flex items-center gap-2"><span className="h-3 w-0.5 bg-accent" />Median</li>
          <li className="flex items-center gap-2"><span className="h-3 w-5 rounded bg-accent/15" />Middle 80% of outcomes</li>
          {p.scenario_change_pct != null && <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rotate-45 bg-warn" />The stress test’s assumption ({signedPct(p.scenario_change_pct, 2)}), {p.scenario_vs_history === "within_historical_range" ? "inside" : "outside"} the historical range</li>}
        </ul>
      </Card>

      <Card className="mt-4 p-5 sm:p-8">
        <p className="h3">Holding by holding</p>
        <p className="mt-1 text-[13px] text-muted">Five-day abnormal return. The shaded bar is the middle 80% of outcomes; the amber tick is the stress test’s assumption for that holding.</p>
        <div className="mt-5 divide-y divide-line-soft">
          {covered.map((c) => (
            <div key={c.symbol} className="grid grid-cols-[4.5rem_1fr] items-center gap-x-4 gap-y-1 py-3.5 sm:grid-cols-[5rem_1fr_9rem_8rem]">
              <div><p className="text-sm font-medium text-ink">{c.symbol}</p><p className="text-xs text-subtle">{c.weight_pct.toFixed(0)}% of portfolio</p></div>
              <RangeRow domain={dom} p10={c.stats!.p10!} p90={c.stats!.p90!} median={c.stats!.median!} marker={c.scenario_shock_pct} />
              <p className="num col-span-2 text-xs text-muted sm:col-span-1 sm:text-right">median <span className="text-ink">{signedPct(c.stats!.median, 2)}</span> · {c.stats!.n} storms</p>
              <p className="col-span-2 text-xs text-muted sm:col-span-1 sm:text-right"><Badge tone={c.stats!.grade === "not_distinguishable_from_zero" ? "neutral" : "accent"}>{gradeLabel(c.stats!.grade)}</Badge></p>
            </div>
          ))}
          {f.assets.filter((x) => !x.covered).map((x) => (
            <div key={x.symbol} className="flex items-center justify-between gap-4 py-3 text-xs text-subtle"><span>{x.symbol} · {x.weight_pct.toFixed(0)}% of portfolio</span><span>no stored price history, so no estimate</span></div>
          ))}
        </div>
      </Card>
    </Section>
  );
}

export function HistoricalEvidence({ r }: { r: QueryPipelineResponse }) {
  const h = r.historical;
  const [all, setAll] = useState(false);
  if (!h || h.status !== "ok" || !h.matches.length) return null;
  const q = r.parsed, period = q.year_from != null;
  const rows = all ? h.matches : h.matches.slice(0, 6);
  const marks = h.matches.map((m) => ({ id: m.storm.storm_id, label: `${titleCase(m.storm.name)} ${m.storm.year} · ${categoryShort(m.storm.max_category_normalized)} · ${m.storm.max_wind_kt} kt`, t: new Date(m.storm.start_datetime).getTime(), category: m.storm.max_category_normalized }));
  return (
    <Section eyebrow={period ? "The historical record" : "Comparable storms"} title={period ? `Storms in ${q.year_from === q.year_to ? q.year_from : `${q.year_from ?? "…"}–${q.year_to ?? "…"}`}` : "The closest matches in 40+ years of records"}
      lead={period ? "From NOAA’s best-track archive, strongest first. Dot size shows strength." : "Found by combining exact filters (place, strength) with semantic similarity to your question."}>
      <Card className="p-5 sm:p-8">
        <StormTimeline storms={marks} ariaLabel={`${marks.length} storms on a timeline`} />
        <ul className="mt-6 divide-y divide-line-soft">
          {rows.map((m) => {
            const s = m.storm, resp = m.market_response.filter((x) => x.car != null), pi = m.physical_impact;
            return (
              <li key={s.storm_id} className="grid gap-x-6 gap-y-2 py-4 sm:grid-cols-[minmax(0,13rem)_1fr]">
                <div>
                  <p className="text-[15px] font-medium text-ink">{titleCase(s.name)} <span className="text-muted">{s.year}</span></p>
                  <p className="mt-0.5 text-xs text-muted">{categoryShort(s.max_category_normalized)} · <span className="num">{s.max_wind_kt}</span> kt · {s.region.replace("North Atlantic", "N. Atlantic")}</p>
                </div>
                <div className="min-w-0 space-y-2">
                  {resp.length > 0 ? (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                      {resp.map((x) => <span key={x.series_key} className="text-muted">{SERIES_SHORT[x.series_key] ?? x.name} <span className={cn("num", (x.car ?? 0) >= 0 ? "text-up" : "text-down")}>{signedPct((x.car ?? 0) * 100)}</span></span>)}
                      <span className="text-subtle">· 5 days after entering the Gulf</span>
                    </div>
                  ) : <p className="text-xs text-subtle">{s.gulf_of_mexico_entered ? "No stored market data for this period." : "Did not enter the Gulf, so no market study was run."}</p>}
                  {pi && pi.max_oil_shut_in_pct != null && (
                    <div className="flex items-center gap-3 text-xs text-muted">
                      <span className="w-40 shrink-0">Gulf oil output shut in</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line-soft"><div className="h-full rounded-full bg-warn/80" style={{ width: `${pi.max_oil_shut_in_pct}%` }} /></div>
                      <span className="num w-10 text-right text-ink-2">{pi.max_oil_shut_in_pct.toFixed(0)}%</span>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {h.matches.length > 6 && <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-[13px] font-medium text-accent hover:underline">{all ? "Show fewer" : `Show all ${h.matches.length}`}</button>}
        {h.notices.length > 0 && <p className="mt-5 rounded-xl border border-line-soft bg-bg-elev px-4 py-3 text-[13px] leading-relaxed text-muted">{h.notices.join(" ")}</p>}
      </Card>
    </Section>
  );
}

// --------------------------------------------------------------------------- 3. live signals
export function Signals({ r }: { r: QueryPipelineResponse }) {
  const m = r.market, n = r.news, w = r.weather;
  const quotes = m?.assets.filter((a) => a.available && a.price != null) ?? [];
  const arts = [...(n?.articles ?? [])].sort((a, b) => ({ high: 0, medium: 1, low: 2 }[a.relevance] - { high: 0, medium: 1, low: 2 }[b.relevance])).slice(0, 3);
  const events = w?.events.map((e) => e.event) ?? [];
  if (!quotes.length && !arts.length && !w) return null;
  return (
    <Section eyebrow="Right now" title="What’s happening in the world today" lead="Live feeds the agents read. They give context, but they are not blended into the evidence numbers, because they have no measured track record here.">
      <div className="grid gap-4 md:grid-cols-3">
        {w && (
          <Card className="p-5">
            <p className="eyebrow">Weather</p>
            {events.length ? (
              <ul className="mt-4 space-y-3">{events.slice(0, 3).map((e) => (
                <li key={e.id}><p className="text-sm font-medium text-ink">{e.name}</p><p className="num mt-0.5 text-xs text-muted">{categoryShort(e.category)} · {e.wind_mph} mph</p><p className="text-xs text-subtle">{e.region}</p></li>
              ))}</ul>
            ) : <p className="mt-4 text-sm text-muted">No active tropical system matches.</p>}
            <p className="mt-4 text-xs leading-relaxed text-subtle">{w.summary}</p>
          </Card>
        )}
        {quotes.length > 0 && (
          <Card className="p-5">
            <div className="flex items-center justify-between"><p className="eyebrow">Markets</p>{m?.meta && <Badge tone={m.meta.source === "live" ? "up" : "warn"}>{m.meta.source === "live" ? "Live" : "Demo"}</Badge>}</div>
            <ul className="mt-4 space-y-3">{quotes.map((a) => (
              <li key={a.symbol} className="flex items-baseline justify-between gap-3">
                <div className="min-w-0"><p className="text-sm font-medium text-ink">{a.symbol}</p><p className="truncate text-xs text-subtle">{a.name}</p></div>
                <div className="text-right"><p className="num text-sm text-ink">{a.price!.toFixed(2)}</p><p className={cn("num text-xs", (a.change_pct ?? 0) >= 0 ? "text-up" : "text-down")}>{signedPct(a.change_pct, 2)}</p></div>
              </li>
            ))}</ul>
          </Card>
        )}
        {n && (
          <Card className="p-5">
            <div className="flex items-center justify-between"><p className="eyebrow">News tone</p>{n.meta && <Badge tone={n.meta.source === "live" ? "up" : "warn"}>{n.meta.source === "live" ? "Live" : "Demo"}</Badge>}</div>
            {n.aggregate_score != null ? <div className="mt-5"><ToneTrack score={n.aggregate_score} /><p className="mt-3 text-xs text-muted">{n.articles.length} articles · overall <span className="text-ink-2">{n.aggregate_sentiment}</span> <span className="num">({n.aggregate_score.toFixed(2)})</span> · keyword scoring, not AI</p></div> : <p className="mt-4 text-sm text-muted">No relevant articles.</p>}
            <ul className="mt-4 space-y-3 border-t border-line-soft pt-4">{arts.map((a) => (
              <li key={a.id}><a href={a.url ?? undefined} target="_blank" rel="noreferrer" className="group block text-[13px] leading-snug text-ink-2 hover:text-ink"><span className="line-clamp-2">{a.title}</span>
                <span className="mt-1 flex items-center gap-1 text-[11px] text-subtle">{a.source_name}{a.published_at && ` · ${timeAgo(a.published_at)}`}{a.url && <ExternalLink className="h-3 w-3 opacity-0 transition group-hover:opacity-100" />}</span></a></li>
            ))}</ul>
          </Card>
        )}
      </div>
    </Section>
  );
}

// --------------------------------------------------------------------------- 4. risk
export function RiskSection({ r }: { r: QueryPipelineResponse }) {
  const d = r.drivers, k = r.risk, ex = r.exposure, sc = r.scenario;
  const sectors = useMemo(() => { const m = new Map<string, number>(); ex?.holdings.forEach((h) => m.set(h.sector, (m.get(h.sector) ?? 0) + h.weight_pct)); return [...m].map(([label, value]) => ({ label, value, tone: label === "Energy" ? ("warn" as const) : ("muted" as const) })).sort((a, b) => b.value - a.value); }, [ex]);
  const hasDrivers = d && d.status === "ok" && d.risk_change;
  if (!hasDrivers && !k && !ex) return null;
  const c = d?.risk_change;
  return (
    <Section eyebrow="Risk" title={hasDrivers ? "Has your risk really changed?" : "How risky is the portfolio?"}
      lead={hasDrivers ? "Volatility is how much your holdings swing day to day. Here is the last year of it, measured on real prices, against its own average." : "Measured in Python from real price history; assumptions are labelled."}>
      <div className="grid gap-4 lg:grid-cols-5">
        {hasDrivers && c && d && (
          <Card className="p-5 sm:p-8 lg:col-span-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2"><p className="h3">Volatility over the last year</p><p className="text-xs text-muted">{d.covered_weight_pct.toFixed(0)}% of the portfolio · prices to {d.prices_as_of}</p></div>
            <div className="mt-4">
              <LineChart ariaLabel="Annualised 20-day volatility of your modeled holdings over the last year" area height={230} yFormat={(v) => `${v.toFixed(0)}%`} refLines={[{ y: c.year_vol_pct, label: "1-year average" }]}
                series={[{ id: "vol", label: "20-day volatility", color: "var(--color-accent)", points: d.rolling_volatility.map((p) => ({ x: new Date(p.date).getTime(), y: p.vol_pct })) }]} />
            </div>
            <div className="mt-7 border-t border-line-soft pt-6">
              <p className="mb-3 text-[13px] text-muted">Today’s <span className="num text-ink">{pct(c.recent_vol_pct)}</span> against everything in the last {Math.round(c.history_days / 21)} months:</p>
              <PercentileTrack percentile={c.history_percentile} label="Recent volatility" />
            </div>
          </Card>
        )}
        <div className={cn("grid gap-4", hasDrivers ? "lg:col-span-2" : "lg:col-span-5 lg:grid-cols-2")}>
          {d && d.holdings.length > 0 && (
            <Card className="p-5 sm:p-6">
              <p className="h3">Which holding drives the risk</p>
              <p className="mt-1 text-[13px] text-muted">Share of recent risk, against the past year (grey).</p>
              <HBars className="mt-5" format={(v) => `${v.toFixed(0)}%`} rows={d.holdings.map((h) => ({ label: h.symbol, sub: `${h.weight_pct.toFixed(0)}% weight`, value: h.risk_share_recent_pct, ghost: h.risk_share_year_pct, tone: "accent" as const }))} max={100} />
            </Card>
          )}
          {sectors.length > 0 && (
            <Card className="p-5 sm:p-6">
              <p className="h3">Where the money sits</p>
              <HBars className="mt-5" rows={sectors} max={100} />
              {ex && <p className="mt-4 text-xs text-muted">Largest position {pct(ex.largest_position_pct, 0)} of the portfolio.</p>}
            </Card>
          )}
        </div>
      </div>

      {k && (
        <Card className="mt-4 p-5 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="h3">The numbers behind it</p>{k.meta.source === "live" ? <Badge tone="up">From real price history</Badge> : <Badge tone="warn">Contains assumptions</Badge>}</div>
          <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-7 lg:grid-cols-4">
            <Stat label="Volatility" value={pct(k.volatility_pct)} hint={k.volatility_method === "historical_return_series" ? "annualised, from stored returns" : "assumed, not measured"} />
            <Stat label="Worst typical day" value={k.historical_var_95_pct != null ? pct(k.historical_var_95_pct, 2) : "—"} hint="1-day 95% value at risk" />
            <Stat label="Risk score" value={`${k.risk_score.toFixed(0)}/100`} hint={`${titleCase(k.risk_level)} · a composite`} />
            {sc && <Stat label="Stress test" value={signedPct(sc.estimated_portfolio_change_pct, 2)} hint={`${usdSigned(sc.estimated_portfolio_change_usd)} · an assumption`} tone="warn" />}
          </dl>
          {k.limitations.length > 0 && <p className="mt-6 text-xs leading-relaxed text-subtle">{k.limitations.join(" ")}</p>}
        </Card>
      )}
    </Section>
  );
}

// --------------------------------------------------------------------------- 5. hedging
export function HedgingSection({ r }: { r: QueryPipelineResponse }) {
  const h = r.hedging;
  if (!h || h.status !== "ok") return null;
  const ok = h.candidates.filter((c) => c.status === "ok" && c.out_of_sample);
  if (!ok.length) return null;
  const best = ok[0], sw = best.storm_windows;
  const dom = sw ? ((): [number, number] => { const m = Math.max(1, ...[sw.unhedged.p10, sw.unhedged.p90, sw.hedged.p10, sw.hedged.p90].map((x) => Math.abs(x ?? 0))); return [-m * 1.1, m * 1.1]; })() : null;
  return (
    <Section eyebrow="Responses" title="Which hedges would have worked" lead="A hedge is a position that moves against your holdings. Each was tested on years of real prices, then re-tested on a year it had never seen, which is the number that matters.">
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="p-5 sm:p-8 lg:col-span-3">
          <p className="h3">Share of risk removed</p>
          <p className="mt-1 text-[13px] text-muted">Bright bar: on unseen data. Grey: on the data used to fit it.</p>
          <HBars className="mt-6" format={(v) => `${v.toFixed(0)}%`} max={100}
            rows={ok.map((c) => ({ label: c.name, sub: `short ${pct(c.notional_pct_of_portfolio, 0)} of portfolio`, value: c.out_of_sample!.variance_reduction_pct, ghost: c.in_sample_variance_reduction_pct ?? undefined, tone: c.out_of_sample!.variance_reduction_pct > 0 ? ("up" as const) : ("down" as const) }))} />
          {ok.some((c) => c.out_of_sample!.variance_reduction_pct <= 0) && <p className="mt-5 text-xs leading-relaxed text-muted">A bar at zero with a negative figure means that hedge looked fine on old data but made things worse on new data.</p>}
        </Card>
        <div className="grid gap-4 lg:col-span-2">
          {sw && dom && sw.unhedged.p10 != null && (
            <Card className="p-5 sm:p-6">
              <p className="h3">In past hurricanes</p>
              <p className="mt-1 text-[13px] text-muted">Five-day outcome with and without the {best.name} hedge ({sw.n} storms, middle 80%).</p>
              <div className="mt-5 space-y-3">
                <div><p className="mb-1 text-xs text-muted">Without hedge <span className="num text-ink-2">{signedPct(sw.unhedged.p10)} to {signedPct(sw.unhedged.p90)}</span></p><RangeRow domain={dom} p10={sw.unhedged.p10!} p90={sw.unhedged.p90!} median={sw.unhedged.median!} /></div>
                <div><p className="mb-1 text-xs text-muted">With hedge <span className="num text-ink-2">{signedPct(sw.hedged.p10)} to {signedPct(sw.hedged.p90)}</span></p><RangeRow domain={dom} p10={sw.hedged.p10!} p90={sw.hedged.p90!} median={sw.hedged.median!} /></div>
              </div>
            </Card>
          )}
          {h.trim_options.length > 0 && (
            <Card className="p-5 sm:p-6">
              <p className="h3">Without derivatives</p>
              <ul className="mt-3 space-y-2 text-[13px] text-muted">{h.trim_options.map((t) => (
                <li key={t.trim_fraction}>Trim <span className="text-ink">{t.symbol}</span> by {Math.round(t.trim_fraction * 100)}% and volatility falls <span className="num text-ink">{t.volatility_reduction_pct.toFixed(0)}%</span> <span className="text-subtle">({pct(t.volatility_before_pct)} → {pct(t.volatility_after_pct)})</span></li>
              ))}</ul>
            </Card>
          )}
        </div>
      </div>
      <p className="mt-4 max-w-3xl text-xs leading-relaxed text-subtle">This is a historical test, not advice. {h.not_modeled.join(" ")}</p>
    </Section>
  );
}

// --------------------------------------------------------------------------- 6. technical details
export function TechnicalDetails({ r }: { r: QueryPipelineResponse }) {
  const p = r.parsed;
  const limits = useMemo(() => Array.from(new Set([...(r.fusion?.limitations ?? []), ...(r.drivers?.limitations ?? []), ...(r.hedging?.limitations ?? []), ...(r.hedging?.not_modeled ?? []), ...(r.risk?.limitations ?? [])])), [r]);
  const ds = r.historical?.dataset;
  return (
    <Section eyebrow="Under the hood" title="Technical details" lead="Everything above can be traced to its source here.">
      <Card className="divide-y divide-line-soft p-2 sm:p-3">
        <div className="p-4">
          <Disclosure summary="How your question was understood">
            <dl>
              <Kv k="Understood by">{p.parser === "llm" ? `${p.llm_model ?? "AI model"} (confidence ${(p.confidence * 100).toFixed(0)}%, self-reported)` : `Rule-based parser (heuristic confidence ${(p.confidence * 100).toFixed(0)}%)`}</Kv>
              <Kv k="Intent">{p.intent.replace("_", " ")}</Kv>
              <Kv k="Event">{p.event_type}{p.event_category ? ` · category ${p.event_category}` : ""}</Kv>
              <Kv k="Place">{p.region ?? "—"}</Kv>
              <Kv k="Period">{p.year_from != null ? `${p.year_from}–${p.year_to}` : "—"}</Kv>
              <Kv k="Also asks about">{p.topics.length ? p.topics.join(", ") : "—"}</Kv>
              <Kv k="About your holdings">{p.uses_portfolio ? "Yes" : "No"}</Kv>
              <Kv k="Agents selected">{p.analysis_steps.join(" → ") || "none"}</Kv>
            </dl>
            {r.parse_notice && <p className="mt-3 text-xs text-warn/90">{r.parse_notice}</p>}
          </Disclosure>
        </div>
        <div className="p-4">
          <Disclosure summary="Data sources and versions">
            <dl>
              {ds && <Kv k="Storm record">{ds.source} {ds.dataset_version} · {ds.storms_in_database} storms{ds.last_ingestion ? ` · loaded ${ds.last_ingestion.slice(0, 10)}` : ""}</Kv>}
              {r.fusion && <Kv k="Evidence">{r.fusion.analogs.source}</Kv>}
              {r.drivers?.prices_as_of && <Kv k="Prices">Stored history to {r.drivers.prices_as_of}</Kv>}
              {r.market?.meta && <Kv k="Quotes">{r.market.meta.source === "live" ? "Live (Finnhub)" : "Demo"}{r.market.meta.notice ? ` · ${r.market.meta.notice}` : ""}</Kv>}
              {r.news?.meta && <Kv k="News">{r.news.meta.source === "live" ? "Live (NewsAPI)" : "Demo"} · {r.news.sentiment_method === "lexicon" ? "keyword-lexicon sentiment" : "demo sentiment"}</Kv>}
              {r.weather?.meta && <Kv k="Weather">{r.weather.meta.source === "live" ? "Live (NOAA NHC)" : "Demo"}</Kv>}
            </dl>
          </Disclosure>
        </div>
        {limits.length > 0 && (
          <div className="p-4">
            <Disclosure summary="Limitations and what is not modeled">
              <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-muted">{limits.map((l) => <li key={l}>{l}</li>)}</ul>
            </Disclosure>
          </div>
        )}
        <div className="p-4">
          <Disclosure summary="How the main numbers were calculated">
            <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-muted">
              <li>A storm’s effect is its five-day return minus what the market model predicted from the S&amp;P 500, starting when it first entered the Gulf (a “cumulative abnormal return”).</li>
              <li>Outcomes are summarised across storms (median, middle 80%). Confidence comes from re-sampling storms 2,000 times; the grade reflects sample size and whether that interval excludes zero.</li>
              <li>Risk and hedge figures use real daily returns. Hedge ratios are fitted on older data and judged on the most recent year.</li>
              <li>Every figure is computed in Python. The AI model only helps understand the question.</li>
            </ul>
          </Disclosure>
        </div>
      </Card>
    </Section>
  );
}
