"use client";

import { useEffect, useRef, useState } from "react";

/** Width of an element in CSS pixels (so SVG charts can render text at its true size). */
export function useWidth<T extends HTMLElement>(initial = 600) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width || initial);
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width) || initial));
    ro.observe(el);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, width] as const;
}
