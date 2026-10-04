"use client";

import { ArrowRight, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Reveal } from "@/components/ui/Reveal";
import { Badge, Button, Card, Container, EmptyState, Skeleton } from "@/components/ui/ui";
import { INTENT_LABEL } from "@/lib/agents";
import { duration, timeAgo } from "@/lib/format";
import { clearHistory, loadHistory, removeEntry, type HistoryEntry } from "@/lib/history";

export default function HistoryClient() {
  const [items, setItems] = useState<HistoryEntry[] | null>(null);
  useEffect(() => setItems(loadHistory()), []);
  const del = (id: string) => { removeEntry(id); setItems(loadHistory()); };
  return (
    <Container className="pb-8 pt-16 sm:pt-24">
      <Reveal className="max-w-3xl">
        <p className="eyebrow mb-4">History</p>
        <h1 className="display text-balance"><span className="text-fade">Every analysis, kept.</span></h1>
        <p className="lead mt-6 max-w-xl">Reopen any past analysis, step timings and evidence included. Stored only in this browser.</p>
      </Reveal>

      <div className="mt-12">
        {items === null ? <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
          : items.length === 0 ? (
            <Card><EmptyState title="Nothing here yet" body="Your analyses will appear here as you run them, with the full report and the exact steps behind each one."
              action={<Button href="/ask" className="mt-2">Ask your first question <ArrowRight className="h-4 w-4" /></Button>} /></Card>
          ) : (
            <>
              <ul className="space-y-3">{items.map((h, i) => (
                <Reveal as="li" key={h.id} delay={Math.min(i, 5) * 0.04}>
                  <Card className="group flex items-stretch transition hover:border-subtle">
                    <Link href={`/history/${h.id}`} className="min-w-0 flex-1 p-5 sm:p-6">
                      <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">{INTENT_LABEL[h.intent] ?? h.intent}</Badge><span className="text-xs text-subtle">{timeAgo(h.createdAt)} · <span className="num">{duration(h.totalMs)}</span> · {h.data.steps.length} agents</span></div>
                      <p className="mt-3 text-[17px] font-medium leading-snug tracking-tight text-ink">{h.headline}</p>
                      <p className="mt-1.5 line-clamp-1 text-sm text-muted">“{h.query}”</p>
                    </Link>
                    <button type="button" onClick={() => del(h.id)} aria-label={`Delete analysis: ${h.query}`} className="grid w-14 shrink-0 place-items-center border-l border-line-soft text-subtle transition hover:text-down"><Trash2 className="h-4 w-4" /></button>
                  </Card>
                </Reveal>))}</ul>
              <div className="mt-8 flex justify-end"><button type="button" onClick={() => { clearHistory(); setItems([]); }} className="text-xs text-subtle transition hover:text-down">Clear all history</button></div>
            </>
          )}
      </div>
    </Container>
  );
}
