"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

/**
 * The visitor's "reduce motion" setting, applied only AFTER mount.
 * The server cannot know it, so the first client render must match the server's; reading it earlier causes hydration mismatches.
 */
export function useReduced(): boolean {
  const real = useReducedMotion();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted && !!real;
}
