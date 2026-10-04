export const linear = (d0: number, d1: number, r0: number, r1: number) => {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
};

/** ~`count` human-friendly tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) return [min];
  const raw = (max - min) / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toFixed(10));
  return out;
}

export function linePath(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

export function nearestIndex(xs: number[], x: number): number {
  let lo = 0, hi = xs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1; else hi = mid;
  }
  return lo > 0 && Math.abs(xs[lo - 1] - x) < Math.abs(xs[lo] - x) ? lo - 1 : lo;
}

/** Deterministic beeswarm: dots keep their x, and stack in y only as much as needed to not overlap. */
export function beeswarm(xs: number[], r: number): number[] {
  const order = xs.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0]);
  const placed: { x: number; y: number }[] = [];
  const ys = new Array<number>(xs.length).fill(0);
  for (const [x, i] of order) {
    let y = 0, k = 0;
    const clash = (yy: number) => placed.some((p) => (p.x - x) ** 2 + (p.y - yy) ** 2 < (2 * r + 1) ** 2);
    while (clash(y)) { k += 1; y = (k % 2 ? 1 : -1) * Math.ceil(k / 2) * (r + 1.5); }
    placed.push({ x, y });
    ys[i] = y;
  }
  return ys;
}
