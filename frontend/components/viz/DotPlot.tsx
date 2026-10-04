"use client";

import { motion } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import { useState } from "react";
import { useWidth } from "@/hooks/useMeasure";
import { beeswarm, linear, niceTicks } from "@/components/viz/scale";

export type Dot = { id: string; label: string; value: number; solid?: boolean };

const R = 5.5;

/**
 * One dot per real past storm, placed by how much the portfolio moved (%).
 * Shaded band = middle 80% of outcomes (10th-90th percentile); line = median; diamond = an assumption being tested.
 */
export default function DotPlot({
  dots, median, p10, p90, marker, ariaLabel, unit = "%", markerLabel = "Assumption",
}: {
  dots: Dot[]; median?: number | null; p10?: number | null; p90?: number | null; marker?: number | null; ariaLabel: string; unit?: string; markerLabel?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const reduce = useReduced();
  const [tip, setTip] = useState<{ d: Dot; x: number; y: number } | null>(null);
  if (!dots.length) return null;

  const W = Math.max(width, 280), pad = 22;
  const vals = [...dots.map((d) => d.value), 0, ...(marker != null ? [marker] : []), ...(p10 != null ? [p10] : []), ...(p90 != null ? [p90] : [])];
  const span = Math.max(...vals) - Math.min(...vals) || 1;
  const x0 = Math.min(...vals) - span * 0.06, x1 = Math.max(...vals) + span * 0.06;
  const X = linear(x0, x1, pad, W - pad);
  const ys = beeswarm(dots.map((d) => X(d.value)), R);
  const half = Math.max(24, ...ys.map((y) => Math.abs(y) + R + 2));
  const H = half * 2 + 38, cy = half + 4;
  const ticks = niceTicks(x0, x1, W < 420 ? 4 : 6);
  const fmt = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(Math.abs(v) < 10 && v % 1 ? 1 : 0)}${unit}`;

  return (
    <div ref={ref} className="relative min-w-0">
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} className="block overflow-visible">
        {p10 != null && p90 != null && <rect x={X(p10)} y={cy - half} width={Math.max(2, X(p90) - X(p10))} height={half * 2} rx={10} fill="var(--color-accent)" opacity={0.08} />}
        <line x1={pad} x2={W - pad} y1={cy} y2={cy} stroke="var(--color-line)" />
        <line x1={X(0)} x2={X(0)} y1={cy - half} y2={cy + half + 8} stroke="var(--color-line-soft)" strokeDasharray="3 4" />
        {median != null && <line x1={X(median)} x2={X(median)} y1={cy - half} y2={cy + half} stroke="var(--color-accent)" strokeWidth={2} strokeLinecap="round" />}
        {ticks.map((t) => (
          <g key={t}><line x1={X(t)} x2={X(t)} y1={cy + half + 4} y2={cy + half + 9} stroke="var(--color-line-soft)" /><text x={X(t)} y={cy + half + 22} textAnchor="middle" fontSize="10.5" fill="var(--color-muted)" className="num">{fmt(t)}</text></g>
        ))}
        {dots.map((d, i) => (
          <motion.circle key={d.id} cx={X(d.value)} cy={cy + ys[i]} r={R} tabIndex={0} aria-label={`${d.label}: ${fmt(d.value)}`}
            fill={d.solid === false ? "var(--color-bg)" : d.value >= 0 ? "var(--color-up)" : "var(--color-down)"} fillOpacity={d.solid === false ? 1 : 0.85}
            stroke={d.solid === false ? (d.value >= 0 ? "var(--color-up)" : "var(--color-down)") : "none"} strokeWidth={1.6}
            initial={reduce ? false : { scale: 0, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }} viewport={{ once: true }}
            transition={{ duration: 0.5, delay: Math.min(i * 0.025, 0.7), ease: [0.16, 1, 0.3, 1] }}
            style={{ transformOrigin: `${X(d.value)}px ${cy + ys[i]}px`, cursor: "pointer" }}
            onPointerEnter={() => setTip({ d, x: X(d.value), y: cy + ys[i] })} onPointerLeave={() => setTip(null)}
            onFocus={() => setTip({ d, x: X(d.value), y: cy + ys[i] })} onBlur={() => setTip(null)} />
        ))}
        {marker != null && (
          <g>
            <path d={`M${X(marker)},${cy - 9} l8,9 l-8,9 l-8,-9 Z`} fill="var(--color-warn)" />
            <text x={X(marker)} y={cy - half - 6} textAnchor="middle" fontSize="10.5" fill="var(--color-warn)">{markerLabel} {fmt(marker)}</text>
          </g>
        )}
      </svg>
      {tip && (
        <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-xl border border-line bg-surface-2/95 px-3 py-1.5 text-xs shadow-xl backdrop-blur"
          style={{ left: Math.min(Math.max(tip.x, 60), W - 60), top: tip.y - R - 6 }}>
          <span className="text-ink">{tip.d.label}</span> <span className="num text-muted">{fmt(tip.d.value)}</span>
        </div>
      )}
    </div>
  );
}
