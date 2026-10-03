"use client";

import { motion } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import { cn } from "@/lib/cn";
import { linear } from "@/components/viz/scale";

/** Horizontal bars: label, bar, value. `ghost` draws a lighter second bar (e.g. in-sample vs out-of-sample). */
export function HBars({ rows, max, format = (v) => v.toFixed(0) + "%", className }: {
  rows: { label: string; sub?: string; value: number; ghost?: number; tone?: "accent" | "up" | "down" | "warn" | "muted" }[]; max?: number; format?: (v: number) => string; className?: string;
}) {
  const reduce = useReduced();
  const top = max ?? Math.max(1, ...rows.flatMap((r) => [Math.abs(r.value), Math.abs(r.ghost ?? 0)]));
  const color = (t?: string) => ({ accent: "bg-accent", up: "bg-up", down: "bg-down", warn: "bg-warn", muted: "bg-subtle" }[t ?? "accent"]);
  return (
    <ul className={cn("space-y-3.5", className)}>
      {rows.map((r) => (
        <li key={r.label}>
          <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="min-w-0 truncate text-ink-2">{r.label}{r.sub && <span className="ml-2 text-xs text-subtle">{r.sub}</span>}</span>
            <span className="num shrink-0 text-ink">{format(r.value)}</span>
          </div>
          <div className="relative h-2 overflow-hidden rounded-full bg-line-soft" role="img" aria-label={`${r.label}: ${format(r.value)}`}>
            {r.ghost != null && <div className="absolute inset-y-0 left-0 rounded-full bg-subtle/50" style={{ width: `${Math.min(100, (Math.max(0, r.ghost) / top) * 100)}%` }} />}
            <motion.div className={cn("absolute inset-y-0 left-0 origin-left rounded-full", color(r.tone))} style={{ width: `${Math.min(100, (Math.max(0, r.value) / top) * 100)}%` }}
              initial={reduce ? false : { scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Where a value sits in its own history: three zones (below normal / normal / elevated) and a marker. */
export function PercentileTrack({ percentile, label }: { percentile: number; label?: string }) {
  const reduce = useReduced();
  const p = Math.min(100, Math.max(0, percentile));
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-line-soft" role="img" aria-label={`${label ?? "Position"}: ${p.toFixed(0)}th percentile of its own history`}>
        <div className="absolute inset-y-0 left-[20%] right-[20%] rounded-full bg-accent/15" />
        <motion.span className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-ink shadow-lg"
          initial={reduce ? false : { left: "50%" }} whileInView={{ left: `${p}%` }} viewport={{ once: true }} style={{ left: `${p}%` }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }} />
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-subtle"><span>calmer than usual</span><span>normal range</span><span>more volatile</span></div>
    </div>
  );
}

/** −1…+1 tone track with a marker (news sentiment). */
export function ToneTrack({ score }: { score: number }) {
  const p = ((Math.max(-1, Math.min(1, score)) + 1) / 2) * 100;
  return (
    <div>
      <div className="relative h-1.5 rounded-full bg-gradient-to-r from-down/50 via-line to-up/50" role="img" aria-label={`Tone ${score.toFixed(2)} on a scale from -1 to +1`}>
        <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-ink" style={{ left: `${p}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-subtle"><span>negative</span><span>positive</span></div>
    </div>
  );
}

/** One row of a range chart on a shared axis: 10th–90th band, median tick, optional assumption marker. */
export function RangeRow({ domain, p10, p90, median, marker, height = 22 }: { domain: [number, number]; p10: number; p90: number; median: number; marker?: number | null; height?: number }) {
  const W = 100, X = linear(domain[0], domain[1], 0, W), zero = X(0);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="h-[22px] w-full overflow-visible" role="img"
      aria-label={`Middle 80% of outcomes ${p10.toFixed(1)}% to ${p90.toFixed(1)}%, median ${median.toFixed(1)}%`}>
      <line x1={0} x2={W} y1={height / 2} y2={height / 2} stroke="#232834" vectorEffect="non-scaling-stroke" />
      <line x1={zero} x2={zero} y1={2} y2={height - 2} stroke="#4a5163" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
      <rect x={X(p10)} y={height / 2 - 5} width={Math.max(0.6, X(p90) - X(p10))} height={10} rx={3} fill="#6ea8ff" opacity={0.28} />
      <line x1={X(median)} x2={X(median)} y1={height / 2 - 7} y2={height / 2 + 7} stroke="#6ea8ff" strokeWidth={2.2} vectorEffect="non-scaling-stroke" />
      {marker != null && <rect x={X(marker) - 0.9} y={height / 2 - 6} width={1.8} height={12} rx={0.4} fill="#f5c45e" transform={`rotate(0)`} />}
    </svg>
  );
}
