"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import type { RunState } from "@/hooks/useAnalysis";
import { buildInsights, type Insight } from "@/lib/insight";
import { Reveal } from "@/components/ui/Reveal";
import { Card } from "@/components/ui/ui";
import PipelineView, { PipelineStrip } from "@/components/pipeline/PipelineView";
import { ExecutiveInsight, FusionEvidence, HedgingSection, HistoricalEvidence, RiskSection, Signals, TechnicalDetails } from "@/components/report/sections";

/** Shows the whole recorded pipeline again, on demand. The strip alone is the one-line summary. */
function PipelineRecap({ run }: { run: RunState }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="mb-5 p-4 sm:px-6 sm:py-4">
      <div className="flex items-start justify-between gap-4">
        <PipelineStrip run={run} />
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[13px] font-medium text-accent hover:underline">
          {open ? "Hide" : "Show"} the steps <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      {open && <div className="mt-6 border-t border-line-soft pt-6"><PipelineView run={run} /></div>}
    </Card>
  );
}

function AlsoFound({ items }: { items: Insight[] }) {
  if (!items.length) return null;
  return (
    <Reveal className="mt-4">
      <p className="eyebrow mb-3 px-1">Also found</p>
      <div className="grid gap-3 md:grid-cols-2">
        {items.slice(0, 4).map((i) => (
          <Card key={i.kind} className="p-5">
            <p className="text-[15px] font-medium leading-snug text-ink">{i.headline}</p>
            <p className="mt-1.5 line-clamp-3 text-[13px] leading-relaxed text-muted">{i.statement}</p>
          </Card>
        ))}
      </div>
    </Reveal>
  );
}

/** The intelligence report: the key finding first, then the evidence behind it, then the technical detail. */
export default function Report({ run }: { run: RunState }) {
  const r = run.result;
  if (!r) return null;
  const { primary, secondary } = buildInsights(r);
  const evidence = [<FusionEvidence key="f" r={r} />, <HistoricalEvidence key="h" r={r} />];
  const riskFirst = primary.kind === "drivers", hedgeFirst = primary.kind === "hedging";
  return (
    <article aria-label="Analysis report">
      <PipelineRecap run={run} />
      <ExecutiveInsight r={r} insight={primary} />
      <AlsoFound items={secondary} />
      {hedgeFirst && <HedgingSection r={r} />}
      {riskFirst && <RiskSection r={r} />}
      {evidence}
      <Signals r={r} />
      {!riskFirst && <RiskSection r={r} />}
      {!hedgeFirst && <HedgingSection r={r} />}
      <TechnicalDetails r={r} />
    </article>
  );
}
