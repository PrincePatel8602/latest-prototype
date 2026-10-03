"use client";

import { motion, useScroll, useTransform, type MotionValue } from "motion/react";
import { useReduced } from "@/hooks/useReduced";
import { useRef } from "react";

function Word({ w, i, n, progress, still }: { w: string; i: number; n: number; progress: MotionValue<number>; still: boolean }) {
  const start = (i / n) * 0.85;
  const opacity = useTransform(progress, [start, start + 0.12], [0.16, 1]);
  return <motion.span style={{ opacity: still ? 1 : opacity }} className="mr-[0.26em] inline-block">{w}</motion.span>;
}

/** A statement that lights up word by word as it scrolls through the middle of the screen. */
export default function ScrollWords({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const reduce = useReduced();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.45"] });
  const words = text.split(" ");
  return (
    <p ref={ref} className={className} aria-label={text}>
      {words.map((w, i) => <Word key={i} w={w} i={i} n={words.length} progress={scrollYProgress} still={reduce} />)}
    </p>
  );
}
