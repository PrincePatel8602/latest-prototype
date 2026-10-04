"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

/**
 * 0 when parallax should be off (reduced motion, small screens), otherwise 1.
 * Components multiply their travel distances by it, so mobile/low-power devices get a flat, fast page.
 */
export function useParallaxStrength(): number {
  const reduce = useReducedMotion();
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 900px) and (pointer: fine)");
    const set = () => setWide(mq.matches);
    set();
    mq.addEventListener("change", set);
    return () => mq.removeEventListener("change", set);
  }, []);
  return reduce || !wide ? 0 : 1;
}
