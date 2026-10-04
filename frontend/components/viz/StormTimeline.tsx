"use client";

import { motion } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import { useState } from "react";
import { useWidth } from "@/hooks/useMeasure";
import { linear, niceTicks } from "@/components/viz/scale";

export type StormMark = { id: string; label: string; t: number; category: number | null; wind?: number | null };

const CAT_COLOR = (c: number | null) => (c == null ? "var(--color-subtle)" : c >= 4 ? "var(--color-down)" : c >= 2 ? "var(--color-warn)" : c >= 1 ? "var(--color-accent)" : "var(--color-subtle)");

/** Storms placed on a time axis; dot size and colour show strength (Saffir-Simpson category). */
export default function StormTimeline({ storms, ariaLabel }: { storms: StormMark[]; ariaLabel: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const reduce = useReduced();
  const [tip, setTip] = useState<StormMark | null>(null);
  if (!storms.length) return null;
  const W = Math.max(width, 280), pad = 20, H = 96, cy = 44;
  const t0 = Math.min(...storms.map((s) => s.t)), t1 = Math.max(...storms.map((s) => s.t));
  const gap = (t1 - t0) || 86400000 * 30;
  const X = linear(t0 - gap * 0.06, t1 + gap * 0.06, pad, W - pad);
  const years = new Set(storms.map((s) => new Date(s.t).getFullYear()));
  const single = years.size === 1;
  const ticks = single
    ? (t1 > t0 ? [t0, (t0 + t1) / 2, t1] : [t0])
    : niceTicks(new Date(t0).getFullYear(), new Date(t1).getFullYear() + 1, W < 480 ? 3 : 6).map((y) => new Date(y, 0, 1).getTime());
  const label = (t: number) => single ? new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : String(new Date(t).getFullYear());
  const r = (c: number | null) => 4 + Math.max(0, c ?? 0) * 1.5;

  return (
    <div ref={ref} className="relative min-w-0">
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} className="block overflow-visible">
        <line x1={pad} x2={W - pad} y1={cy + 24} y2={cy + 24} stroke="var(--color-line)" />
        {ticks.map((t) => <g key={t}><line x1={X(t)} x2={X(t)} y1={cy + 24} y2={cy + 29} stroke="var(--color-line-soft)" /><text x={X(t)} y={cy + 44} textAnchor="middle" fontSize="10.5" fill="var(--color-muted)">{label(t)}</text></g>)}
        {storms.map((s, i) => (
          <motion.circle key={s.id} cx={X(s.t)} cy={cy + 24 - r(s.category) - 2} r={r(s.category)} fill={CAT_COLOR(s.category)} fillOpacity={0.82} tabIndex={0} aria-label={s.label}
            initial={reduce ? false : { scale: 0, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }} viewport={{ once: true }}
            transition={{ duration: 0.5, delay: Math.min(i * 0.03, 0.8), ease: [0.16, 1, 0.3, 1] }}
            style={{ transformOrigin: `${X(s.t)}px ${cy + 24 - r(s.category) - 2}px`, cursor: "pointer" }}
            onPointerEnter={() => setTip(s)} onPointerLeave={() => setTip(null)} onFocus={() => setTip(s)} onBlur={() => setTip(null)} />
        ))}
      </svg>
      {tip && <div className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-xl border border-line bg-surface-2/95 px-3 py-1.5 text-xs text-ink shadow-xl backdrop-blur" style={{ left: Math.min(Math.max(X(tip.t), 70), W - 70), top: 0 }}>{tip.label}</div>}
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        {[["Tropical storm / Cat 1", "var(--color-accent)"], ["Cat 2–3", "var(--color-warn)"], ["Cat 4–5", "var(--color-down)"]].map(([l, c]) => <li key={l} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{l}</li>)}
      </ul>
    </div>
  );
}
