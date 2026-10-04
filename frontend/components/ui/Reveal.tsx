"use client";

import { motion } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import type { ReactNode } from "react";

/** Fade + small rise (+ a touch of blur) when scrolled into view. Does nothing for reduced-motion users. */
export function Reveal({ children, delay = 0, y = 18, className, once = true, as = "div" }: {
  children: ReactNode; delay?: number; y?: number; className?: string; once?: boolean; as?: "div" | "section" | "li" | "article";
}) {
  const reduce = useReduced();
  const M = motion[as];
  if (reduce) return <M className={className}>{children}</M>;
  return (
    <M
      className={className}
      initial={{ opacity: 0, y, filter: "blur(6px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once, margin: "0px 0px -12% 0px" }}
      transition={{ duration: 0.7, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </M>
  );
}
