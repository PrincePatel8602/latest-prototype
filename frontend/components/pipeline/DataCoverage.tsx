"use client";

import { useApi } from "@/hooks/useApi";
import { getCoverage, getHistoricalStatus } from "@/lib/api";
import { dateShort } from "@/lib/format";
import Live from "@/components/ui/Live";
import { Card, Skeleton, Stat } from "@/components/ui/ui";

/** What the system actually holds, straight from the database. */
export default function DataCoverage() {
  const cov = useApi(getCoverage), st = useApi(getHistoricalStatus);
  const hist = st.state.status === "success" ? st.state.data : null;
  return (
    <Live state={cov.state} onRetry={cov.reload} errorTitle="Data coverage isn’t available" skeleton={<div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>}>
      {(c) => {
        const bySource = new Map<string, { n: number; last: string }>();
        c.market.detail.forEach((s) => { const e = bySource.get(s.source) ?? { n: 0, last: "" }; bySource.set(s.source, { n: e.n + 1, last: s.last_date && s.last_date > e.last ? s.last_date : e.last }); });
        const SRC: Record<string, string> = { eia: "EIA oil & gas prices", fred: "FRED macro series", yahoo: "Yahoo Finance equities & ETFs" };
        return (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card className="p-6"><Stat label="Storms in the record" value={c.storms.count.toLocaleString()} hint={`${c.storms.track_points.toLocaleString()} track points · ${c.storms.source}`} /></Card>
              <Card className="p-6"><Stat label="Daily price observations" value={c.market.observations.toLocaleString()} hint={`${c.market.series} series from EIA, FRED and Yahoo Finance`} /></Card>
              <Card className="p-6"><Stat label="Storm event studies" value={c.event_study.results.toLocaleString()} hint="storm × asset market responses, computed in Python" /></Card>
              <Card className="p-6"><Stat label="Production shut-in reports" value={c.shut_ins.reports.toLocaleString()} hint={`${c.shut_ins.storms} storms · ${c.shut_ins.source}`} /></Card>
            </div>
            <Card className="mt-4 p-6">
              <p className="eyebrow mb-4">Freshness</p>
              <ul className="grid gap-x-10 gap-y-3 text-sm sm:grid-cols-2">
                {[...bySource].map(([k, v]) => <li key={k} className="flex justify-between gap-4 border-b border-line-soft pb-3"><span className="text-ink-2">{SRC[k] ?? k}</span><span className="num text-muted">to {v.last ? dateShort(v.last) : "—"}</span></li>)}
                {hist?.last_ingestion && <li className="flex justify-between gap-4 border-b border-line-soft pb-3"><span className="text-ink-2">Storm record ({hist.last_ingestion.dataset_version})</span><span className="num text-muted">loaded {dateShort(hist.last_ingestion.started_at)}</span></li>}
                {hist?.pinecone.configured && <li className="flex justify-between gap-4 border-b border-line-soft pb-3"><span className="text-ink-2">Semantic index (Pinecone)</span><span className="num text-muted">{hist.pinecone.records?.toLocaleString() ?? "—"} storms</span></li>}
              </ul>
            </Card>
          </>
        );
      }}
    </Live>
  );
}
