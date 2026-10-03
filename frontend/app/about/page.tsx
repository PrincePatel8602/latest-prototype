import type { Metadata } from "next";
import { Reveal } from "@/components/ui/Reveal";
import { Badge, Button, Card, Container, SectionHeading } from "@/components/ui/ui";

export const metadata: Metadata = { title: "About", description: "How to read FinSight’s evidence, where the data comes from, and what it deliberately does not claim." };

const GRADES = [
  ["Not enough data", "neutral", "Fewer than five comparable storms. FinSight offers no estimate rather than a shaky one."],
  ["No clear effect", "neutral", "Enough storms to judge, and the average effect can’t be told apart from zero. This is a result, not a failure: it means history does not show a reliable move."],
  ["Weak signal", "warn", "The effect looks real in the sample, but fewer than ten storms back it. Treat it as a hint."],
  ["Indicative", "accent", "Ten or more storms, and the statistical range excludes zero. It still describes the past; it does not prove a cause or predict the next storm."],
] as const;

const SOURCES = [
  ["NOAA IBTrACS v04r01", "Every North Atlantic tropical cyclone since 1980: position, wind and pressure every few hours. The official best-track archive."],
  ["NOAA National Hurricane Center", "Live positions of active systems. Current position only; no forecast track is invented."],
  ["EIA · FRED", "Daily oil and natural-gas spot prices, and macro series such as rates and the dollar."],
  ["Yahoo Finance", "Daily prices for the equities and ETFs in the portfolio. An unofficial feed, flagged as such."],
  ["BSEE", "How much Gulf of Mexico oil and gas output was shut in during storms, 2011 onward, from the agency’s own reports."],
  ["NewsAPI · Finnhub", "Recent headlines and current quotes. Labelled live or demo on every result."],
];

const LIMITS = [
  "FinSight describes what happened in comparable past storms. It does not predict the next one, and it is not investment advice.",
  "Storm records start in 1980 and shut-in reports in 2011. Only holdings with stored price history are measured; the rest are named as not covered.",
  "There are only a few dozen hurricanes in the Gulf, and storm seasons cluster. Small samples are shown as small samples.",
  "The record holds storm tracks and intensity, not flooding, damage or casualties. If you ask about those, the answer says so.",
  "Market moves are measured against the S&P 500 alone. Oil politics, earnings and other news are not removed.",
  "Hedge tests do not include trading costs, margin, taxes or options prices.",
  "News tone comes from a transparent keyword list, not an AI model, and the interface labels it that way.",
];

const GLOSSARY = [
  ["Volatility", "How much a price swings day to day, scaled to a year. Higher means a bumpier ride."],
  ["Abnormal return", "How much an asset moved beyond what the wider market explained. It isolates the storm’s effect from a general rally or sell-off."],
  ["Percentile", "Where today sits among the past. The 90th percentile means it is higher than 90% of the days on record."],
  ["Value at risk", "The loss you would exceed on the worst 5% of days, from history. A guide to bad days, not a limit."],
  ["Hedge ratio", "How much of an offsetting position would have cancelled the most risk."],
  ["Out of sample", "Judged on data the method never saw while being fitted. It is the honest test of a hedge."],
  ["Basis risk", "The part of your risk a hedge cannot remove, because the two do not move perfectly together."],
];

export default function Page() {
  return (
    <Container className="pb-8 pt-16 sm:pt-24">
      <Reveal className="max-w-3xl">
        <p className="eyebrow mb-4">About</p>
        <h1 className="display text-balance"><span className="text-fade">Built to be checked.</span></h1>
        <p className="lead mt-6 max-w-2xl">FinSight turns a plain-English question into an evidence-based analysis, and shows its work at every step. This page explains how to read it, where the data comes from, and what it deliberately does not claim.</p>
      </Reveal>

      <section className="mt-24">
        <SectionHeading eyebrow="Reading the evidence" title="Four grades, in plain words." lead="Every estimate carries a grade based on how many storms stand behind it and what the statistics say." />
        <div className="mt-10 grid gap-3 md:grid-cols-2">{GRADES.map(([g, tone, d], i) => (
          <Reveal key={g} delay={i * 0.05}><Card className="h-full p-6"><Badge tone={tone}>{g}</Badge><p className="mt-4 text-[15px] leading-relaxed text-ink-2">{d}</p></Card></Reveal>))}</div>
      </section>

      <section className="mt-24">
        <SectionHeading eyebrow="Where it comes from" title="Named sources, shown with every result." />
        <dl className="mt-8 divide-y divide-line-soft border-y border-line-soft">{SOURCES.map(([n, d]) => (
          <Reveal key={n}><div className="grid gap-1 py-5 sm:grid-cols-[16rem_1fr] sm:gap-8"><dt className="text-[15px] font-medium text-ink">{n}</dt><dd className="text-[15px] leading-relaxed text-muted">{d}</dd></div></Reveal>))}</dl>
      </section>

      <section className="mt-24">
        <SectionHeading eyebrow="Honest limits" title="What it does not claim." />
        <ul className="mt-8 space-y-4">{LIMITS.map((l) => <Reveal as="li" key={l}><div className="flex gap-4 text-[15px] leading-relaxed text-ink-2"><span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-warn" />{l}</div></Reveal>)}</ul>
      </section>

      <section className="mt-24">
        <SectionHeading eyebrow="Glossary" title="The few terms you will see." />
        <dl className="mt-8 grid gap-x-12 gap-y-7 md:grid-cols-2">{GLOSSARY.map(([t, d]) => <Reveal key={t}><dt className="text-[15px] font-medium text-ink">{t}</dt><dd className="mt-1.5 text-[14px] leading-relaxed text-muted">{d}</dd></Reveal>)}</dl>
      </section>

      <Reveal className="mt-28 text-center"><Button href="/ask" size="lg">Ask a question</Button></Reveal>
    </Container>
  );
}
