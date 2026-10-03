"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

/** Every animation in the app respects the visitor's "reduce motion" setting. */
export default function Providers({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
