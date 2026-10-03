"use client";

import { AnimatePresence, motion } from "motion/react";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/ui";

export const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/ask", label: "Ask" },
  { href: "/intelligence", label: "How it works" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/history", label: "History" },
  { href: "/about", label: "About" },
] as const;

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
        <rect x="0.5" y="0.5" width="25" height="25" rx="7.5" fill="#11141b" stroke="#2c3342" />
        <path d="M5.5 16.5l4.2-4.6 3.3 2.9 7.5-7.9" fill="none" stroke="#6ea8ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20.5" cy="6.9" r="1.7" fill="#6ea8ff" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight text-ink">FinSight</span>
    </span>
  );
}

export default function Nav() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <header className={cn("sticky top-0 z-50 transition-colors duration-300", scrolled || open ? "border-b border-line/70 bg-bg/75 backdrop-blur-xl" : "border-b border-transparent")}>
      <nav aria-label="Primary" className="mx-auto flex h-14 max-w-7xl items-center justify-between px-5 sm:px-8">
        <Link href="/" aria-label="FinSight home"><Logo /></Link>

        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <li key={l.href} className="relative">
              <Link href={l.href} aria-current={active(l.href) ? "page" : undefined}
                className={cn("relative block rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors", active(l.href) ? "text-ink" : "text-muted hover:text-ink")}>
                {active(l.href) && <motion.span layoutId="nav-pill" className="absolute inset-0 -z-10 rounded-full bg-surface-2" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
                {l.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2">
          <Button href="/ask" className="hidden !h-9 !px-4 text-[13px] sm:inline-flex">Ask a question</Button>
          <button type="button" aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open} onClick={() => setOpen((o) => !o)}
            className="grid h-9 w-9 place-items-center rounded-full border border-line text-ink md:hidden">
            {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </nav>

      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }} className="overflow-hidden md:hidden">
            <ul className="mx-auto max-w-7xl space-y-1 px-5 pb-5 pt-1">
              {LINKS.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className={cn("block rounded-xl px-4 py-3 text-base font-medium", active(l.href) ? "bg-surface-2 text-ink" : "text-muted")}>{l.label}</Link>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
