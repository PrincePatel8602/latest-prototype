"use client";

import { motion, useInView } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import { useId, useMemo, useRef, useState } from "react";
import { useWidth } from "@/hooks/useMeasure";
import { linePath, linear, nearestIndex, niceTicks } from "@/components/viz/scale";

export type LinePoint = { x: number; y: number };   // x = timestamp (ms)
export type LineSeries = { id: string; label: string; color: string; points: LinePoint[]; dashed?: boolean };

const M = { l: 46, r: 14, t: 12, b: 26 };

export default function LineChart({
  series, height = 240, yFormat = (v) => v.toFixed(0), xFormat = (t) => new Date(t).toLocaleDateString("en-US", { month: "short", year: "2-digit" }),
  refLines = [], area, ariaLabel, yDomain, legend = true,
}: {
  series: LineSeries[]; height?: number; yFormat?: (v: number) => string; xFormat?: (t: number) => string;
  refLines?: { y: number; label: string }[]; area?: boolean; ariaLabel: string; yDomain?: [number, number]; legend?: boolean;
}) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const inViewRef = useRef<HTMLDivElement>(null);
  const inView = useInView(inViewRef, { once: true, margin: "0px 0px -10% 0px" });
  const reduce = useReduced();
  const [hover, setHover] = useState<number | null>(null);
  const gid = useId().replace(/:/g, "");

  const all = series.flatMap((s) => s.points);
  const g = useMemo(() => {
    if (!all.length) return null;
    const x0 = Math.min(...all.map((p) => p.x)), x1 = Math.max(...all.map((p) => p.x));
    let y0 = yDomain?.[0] ?? Math.min(...all.map((p) => p.y), ...refLines.map((r) => r.y));
    let y1 = yDomain?.[1] ?? Math.max(...all.map((p) => p.y), ...refLines.map((r) => r.y));
    if (!yDomain) { const pad = (y1 - y0) * 0.1 || 1; y0 -= pad; y1 += pad; }
    return { x0, x1, y0, y1 };
  }, [all, yDomain, refLines]);

  if (!g || !series.length) return null;
  const W = Math.max(width, 260), H = height;
  const X = linear(g.x0, g.x1, M.l, W - M.r), Y = linear(g.y0, g.y1, H - M.b, M.t);
  const yt = niceTicks(g.y0, g.y1, 4);
  const xt = [0, 1 / 3, 2 / 3, 1].map((f) => g.x0 + f * (g.x1 - g.x0));
  const lead = series[0].points;
  const hp = hover != null ? lead[Math.min(hover, lead.length - 1)] : null;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const t = g.x0 + ((e.clientX - r.left) / r.width) * (g.x1 - g.x0);
    setHover(nearestIndex(lead.map((p) => p.x), t));
  };

  return (
    <div ref={inViewRef} className="min-w-0">
      {legend && series.length > 1 && (
        <ul className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          {series.map((s) => <li key={s.id} className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: s.color }} />{s.label}</li>)}
        </ul>
      )}
      <div ref={wrap} className="relative min-w-0">
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} className="block overflow-visible">
          <defs>
            {series.map((s) => (
              <linearGradient key={s.id} id={`${gid}-${s.id}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity="0.22" /><stop offset="100%" stopColor={s.color} stopOpacity="0" />
              </linearGradient>
            ))}
          </defs>
          {yt.map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={Y(v)} y2={Y(v)} stroke="var(--color-line)" />
              <text x={M.l - 8} y={Y(v) + 4} textAnchor="end" className="num" fontSize="10.5" fill="var(--color-muted)">{yFormat(v)}</text>
            </g>
          ))}
          {xt.map((t, i) => <text key={i} x={X(t)} y={H - 6} textAnchor={i === 0 ? "start" : i === xt.length - 1 ? "end" : "middle"} fontSize="10.5" fill="var(--color-muted)">{xFormat(t)}</text>)}
          {refLines.map((r) => (
            <g key={r.label}>
              <line x1={M.l} x2={W - M.r} y1={Y(r.y)} y2={Y(r.y)} stroke="var(--color-line-soft)" strokeDasharray="3 4" />
              <text x={W - M.r} y={Y(r.y) - 5} textAnchor="end" fontSize="10.5" fill="var(--color-subtle)">{r.label}</text>
            </g>
          ))}
          {series.map((s) => {
            const pts = s.points.map((p) => [X(p.x), Y(p.y)] as [number, number]);
            const d = linePath(pts);
            return (
              <g key={s.id}>
                {area && <path d={`${d} L${pts[pts.length - 1][0]},${H - M.b} L${pts[0][0]},${H - M.b} Z`} fill={`url(#${gid}-${s.id})`} opacity={inView || reduce ? 1 : 0} style={{ transition: "opacity .8s ease .3s" }} />}
                <motion.path d={d} fill="none" stroke={s.color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "4 4" : undefined}
                  initial={reduce ? false : { pathLength: 0 }} animate={reduce || inView ? { pathLength: 1 } : { pathLength: 0 }} transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }} />
                <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={3.2} fill={s.color} />
              </g>
            );
          })}
          {hp && <line x1={X(hp.x)} x2={X(hp.x)} y1={M.t} y2={H - M.b} stroke="var(--color-line-soft)" />}
          {hp && series.map((s) => { const p = s.points[Math.min(hover!, s.points.length - 1)]; return <circle key={s.id} cx={X(p.x)} cy={Y(p.y)} r={4} fill="var(--color-bg)" stroke={s.color} strokeWidth={2} />; })}
          <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
        {hp && (
          <div className="pointer-events-none absolute z-10 rounded-xl border border-line bg-surface-2/95 px-3 py-2 text-xs shadow-xl backdrop-blur"
            style={{ left: Math.min(Math.max(X(hp.x) - 60, 0), W - 140), top: 0 }}>
            <p className="text-muted">{new Date(hp.x).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</p>
            {series.map((s) => { const p = s.points[Math.min(hover!, s.points.length - 1)]; return (
              <p key={s.id} className="num mt-0.5 flex items-center gap-2 text-ink"><span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />{series.length > 1 && <span className="text-muted">{s.label}</span>}{yFormat(p.y)}</p>
            ); })}
          </div>
        )}
      </div>
    </div>
  );
}
