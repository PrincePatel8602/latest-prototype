"use client";

import { useEffect, useState } from "react";
import DataCoverage from "@/components/pipeline/DataCoverage";
import SystemMap from "@/components/pipeline/SystemMap";
import { Reveal } from "@/components/ui/Reveal";
import { Card, Container, SectionHeading } from "@/components/ui/ui";
import { latestEntry, type HistoryEntry } from "@/lib/history";

const SPLIT = [
  { who: "The AI model", does: ["Understands your question", "Extracts the goal, event, place and period", "Never touches a number"] },
  { who: "Python", does: ["Calculates every figure", "Volatility, exposure, event studies, hedge tests", "Same inputs always give the same outputs"] },
  { who: "The database", does: ["40 years of storms and prices", "Semantic search over every storm", "Everything traced to a named source"] },
];

export default function IntelligenceClient() {
  const [entry, setEntry] = useState<HistoryEntry | null>(null);
  useEffect(() => setEntry(latestEntry()), []);
  return (
    <Container wide className="pb-8 pt-12 sm:pt-16">
      <Reveal className="max-w-3xl">
        <p className="eyebrow mb-4">How it works</p>
        <h1 className="h1 text-balance"><span className="text-fade">The whole system, in one picture.</span></h1>
        <p className="lead mt-4 max-w-2xl">A question flows left to right: understood, routed to the right specialists, analysed in code, written up as evidence. Select any step to see what it does.</p>
      </Reveal>

      <Reveal className="mt-10"><SystemMap entry={entry} /></Reveal>

      <section className="mt-28">
        <SectionHeading eyebrow="Who does what" title="The AI understands. Code does the maths." lead="A language model is good at reading a question and bad at arithmetic. So FinSight keeps them apart." />
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {SPLIT.map((s, i) => (
            <Reveal key={s.who} delay={i * 0.08}><Card className="h-full p-6"><p className="h3">{s.who}</p><ul className="mt-4 space-y-2.5">{s.does.map((d) => <li key={d} className="flex gap-2.5 text-[14px] leading-snug text-muted"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" />{d}</li>)}</ul></Card></Reveal>
          ))}
        </div>
      </section>

      <section className="mt-28">
        <SectionHeading eyebrow="What it holds" title="The data behind every answer." lead="Read from the database right now, not a brochure." />
        <div className="mt-10"><DataCoverage /></div>
      </section>
    </Container>
  );
}
