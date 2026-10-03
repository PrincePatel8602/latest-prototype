"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Report from "@/components/report/Report";
import { Button, Card, Container, EmptyState, Skeleton } from "@/components/ui/ui";
import { runFromEntry } from "@/hooks/useAnalysis";
import { dateShort } from "@/lib/format";
import { getEntry, type HistoryEntry } from "@/lib/history";

export default function HistoryDetail() {
  const { id } = useParams<{ id: string }>();
  const [entry, setEntry] = useState<HistoryEntry | null | undefined>(undefined);
  useEffect(() => setEntry(getEntry(id)), [id]);
  return (
    <Container className="pb-8 pt-12 sm:pt-16">
      <Link href="/history" className="mb-8 inline-flex items-center gap-2 text-[13px] text-muted transition hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />All history</Link>
      {entry === undefined ? <Skeleton className="h-72 w-full" />
        : entry === null ? <Card><EmptyState title="This analysis isn’t in this browser" body="History is stored locally, so it can’t be opened on another device or after clearing site data." action={<Button href="/ask" className="mt-2">Run a new analysis</Button>} /></Card>
        : (
          <>
            <header className="mb-8 max-w-3xl"><p className="eyebrow mb-3">Saved analysis · {dateShort(entry.createdAt)}</p><p className="text-lg leading-snug text-muted">“{entry.query}”</p></header>
            <Report run={runFromEntry(entry)} />
          </>
        )}
    </Container>
  );
}
