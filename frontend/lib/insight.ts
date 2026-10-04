import { pct, signedPct, titleCase, usdSigned } from "@/lib/format";
import type { QueryPipelineResponse } from "@/types/agents";

// Turns the REAL fields of an analysis into the report's headline and findings. Deterministic rules only:
// no text is generated, every number is read from the backend result.

export type Tone = "calm" | "watch" | "alert" | "info";
export interface Insight {
  kind: "fusion" | "drivers" | "hedging" | "historical" | "weather" | "market" | "news" | "none";
  headline: string; statement: string; tone: Tone;
  metrics: { label: string; value: string; hint?: string }[];
}

const GRADE: Record<string, string> = {
  insufficient_data: "Not enough data", not_distinguishable_from_zero: "No clear effect", weak_signal: "Weak signal", indicative: "Indicative",
};
export const gradeLabel = (g: string) => GRADE[g] ?? g;

function fusion(r: QueryPipelineResponse): Insight | null {
  const f = r.fusion, p = f?.portfolio;
  if (!f || f.status !== "ok" || !p) return null;
  const a = p.all_analogs;
  const base = `Across ${a.n} comparable storms, the holdings we can measure (${p.covered_weight_pct.toFixed(0)}% of your portfolio) moved a median of ${signedPct(a.median, 2)} over five days, with most outcomes between ${signedPct(a.p10)} and ${signedPct(a.p90)}.`;
  const metrics = [
    { label: "Median, 5 days", value: signedPct(a.median, 2), hint: `${usdSigned(p.median_usd ?? 0)} on your portfolio` },
    { label: "Typical range", value: `${signedPct(a.p10)} to ${signedPct(a.p90)}`, hint: "middle 80% of past storms" },
    { label: "Storms compared", value: String(a.n), hint: `${p.independent_only.n} independent` },
    { label: "Evidence", value: gradeLabel(a.grade), hint: "from sample size and statistics" },
  ];
  if (a.grade === "not_distinguishable_from_zero")
    return { kind: "fusion", tone: "calm", headline: "Past storms like this did not reliably move your portfolio", statement: `${base} That is statistically indistinguishable from no effect at all.`, metrics };
  const down = (a.median ?? 0) < 0;
  return { kind: "fusion", tone: down ? "watch" : "info", headline: `Comparable storms tended to ${down ? "hurt" : "help"} your portfolio`,
    statement: `${base} The evidence is ${gradeLabel(a.grade).toLowerCase()}.`, metrics };
}

function drivers(r: QueryPipelineResponse): Insight | null {
  const d = r.drivers, c = d?.risk_change;
  if (!d || d.status !== "ok" || !c) return null;
  const lead = d.holdings[0];
  const headline = { elevated: "Your portfolio risk is higher than usual", typical: "Your portfolio risk is in its normal range", subdued: "Your portfolio is calmer than usual" }[c.classification];
  return { kind: "drivers", tone: c.classification === "elevated" ? "alert" : "calm", headline,
    statement: `Over the last ${c.window_days} trading days, volatility was ${pct(c.recent_vol_pct)} against ${pct(c.year_vol_pct)} over the past year, which ranks at the ${c.history_percentile.toFixed(0)}th percentile of its own history.${lead ? ` ${lead.symbol} drives ${lead.risk_share_recent_pct.toFixed(0)}% of the recent risk on a ${lead.weight_pct.toFixed(0)}% weight.` : ""}`,
    metrics: [
      { label: `Volatility, ${c.window_days} days`, value: pct(c.recent_vol_pct), hint: "annualised" },
      { label: "Past year", value: pct(c.year_vol_pct) },
      { label: "Rank in own history", value: `${c.history_percentile.toFixed(0)}th`, hint: "percentile" },
      { label: "Biggest driver", value: lead?.symbol ?? "—", hint: lead ? `${lead.risk_share_recent_pct.toFixed(0)}% of risk` : undefined },
    ] };
}

function hedging(r: QueryPipelineResponse): Insight | null {
  const h = r.hedging;
  if (!h || h.status !== "ok") return null;
  const best = h.candidates.find((c) => c.rank === 1);
  if (!best || !best.out_of_sample) return null;
  const oos = best.out_of_sample.variance_reduction_pct;
  if (oos <= 0) return { kind: "hedging", tone: "info", headline: "No tested hedge held up", statement: "None of the candidate hedges reduced your risk out of sample, so history does not support one.", metrics: [] };
  return { kind: "hedging", tone: "info", headline: `${best.name} would have been the most effective hedge`,
    statement: `Shorting about ${pct(best.notional_pct_of_portfolio, 0)} of your portfolio in ${best.name} would historically have removed ${pct(oos, 0)} of risk on data it had not seen (${pct(best.in_sample_variance_reduction_pct, 0)} in-sample). Costs, options and taxes are not modeled.`,
    metrics: [
      { label: "Risk removed", value: pct(oos, 0), hint: "out of sample" },
      { label: "Position size", value: pct(best.notional_pct_of_portfolio, 0), hint: "of portfolio value" },
      { label: "Volatility", value: `${pct(best.before?.volatility_pct)} → ${pct(best.after?.volatility_pct)}` },
      { label: "Worst day", value: `${signedPct(best.before?.worst_day_pct)} → ${signedPct(best.after?.worst_day_pct)}` },
    ] };
}

function historical(r: QueryPipelineResponse): Insight | null {
  const h = r.historical;
  if (!h || h.status !== "ok" || !h.matches.length) return null;
  const q = r.parsed, strongest = [...h.matches].sort((a, b) => (b.storm.max_wind_kt ?? 0) - (a.storm.max_wind_kt ?? 0))[0].storm;
  const kind = q.event_type === "hurricane" ? "hurricanes" : "tropical systems";
  const period = q.year_from != null ? (q.year_from === q.year_to ? String(q.year_from) : `${q.year_from ?? "…"}–${q.year_to ?? "…"}`) : null;
  const cat = strongest.max_category_normalized;
  const strongestText = `${titleCase(strongest.name)} ${strongest.year}${cat != null && cat >= 1 ? `, Category ${cat}` : ""}, with winds up to ${strongest.max_wind_kt} kt`;
  return { kind: "historical", tone: "info", headline: period ? `${h.matches.length} ${kind} in ${period}` : `${h.matches.length} comparable past storms found`,
    statement: `The strongest was ${strongestText}.${period ? " They are ordered strongest first." : ""}${h.notices.length ? ` ${h.notices[h.notices.length - 1]}` : ""}`,
    metrics: [
      { label: "Storms found", value: String(h.matches.length) },
      { label: "Strongest", value: titleCase(strongest.name), hint: cat != null && cat >= 1 ? `Category ${cat}` : "tropical storm" },
      { label: "Top wind", value: `${strongest.max_wind_kt} kt`, hint: `${strongest.max_wind_mph} mph` },
      { label: "Record", value: "NOAA IBTrACS", hint: h.dataset.dataset_version },
    ] };
}

function weather(r: QueryPipelineResponse): Insight | null {
  const w = r.weather, e = w?.primary_event;
  if (!w || !e) return null;
  return { kind: "weather", tone: e.severity === "HIGH" || e.severity === "EXTREME" ? "watch" : "info", headline: `Active now: ${e.name}`,
    statement: `${e.name} is a Category ${e.category} system (${e.wind_mph} mph) in the ${e.region}. ${w.summary}`,
    metrics: [{ label: "Strength", value: `Cat ${e.category}`, hint: `${e.wind_mph} mph` }, { label: "Severity", value: e.severity }] };
}

const ORDER: Record<string, Array<(r: QueryPipelineResponse) => Insight | null>> = {
  hedging: [hedging, fusion, drivers, historical, weather],
  explain_risk: [drivers, hedging, fusion],
  portfolio_risk: [drivers, hedging, fusion],
  historical_search: [historical, fusion],
  event_impact: [fusion, historical, weather, drivers],
};

/** The strongest insight first, then supporting findings from the other agents that produced something. */
export function buildInsights(r: QueryPipelineResponse): { primary: Insight; secondary: Insight[] } {
  const order = ORDER[r.parsed.intent] ?? [fusion, drivers, hedging, historical, weather];
  const all = [...order, fusion, drivers, hedging, historical, weather].map((f) => f(r)).filter((x): x is Insight => !!x);
  const seen = new Set<string>();
  const uniq = all.filter((i) => (seen.has(i.kind) ? false : (seen.add(i.kind), true)));
  if (uniq.length) return { primary: uniq[0], secondary: uniq.slice(1) };
  const text = r.market?.summary ?? r.news?.summary ?? r.parsed.warnings[0] ?? "No analysis could be produced for this question.";
  return { primary: { kind: "none", tone: "info", headline: r.parsed.warnings.length ? "We couldn't tell what to analyse" : "Here is what the agents found", statement: text, metrics: [] }, secondary: [] };
}
