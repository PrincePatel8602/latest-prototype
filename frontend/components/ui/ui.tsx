import Link from "next/link";
import { AlertTriangle, ChevronDown, Inbox, RotateCw } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Container({ children, className, wide }: { children: ReactNode; className?: string; wide?: boolean }) {
  return <div className={cn("mx-auto w-full px-5 sm:px-8", wide ? "max-w-7xl" : "max-w-6xl", className)}>{children}</div>;
}

type Tone = "neutral" | "accent" | "up" | "down" | "warn";
const TONES: Record<Tone, string> = {
  neutral: "border-line text-muted",
  accent: "border-accent/30 bg-accent/10 text-accent",
  up: "border-up/25 bg-up/10 text-up",
  down: "border-down/25 bg-down/10 text-down",
  warn: "border-warn/25 bg-warn/10 text-warn",
};

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium leading-5", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Dot({ tone = "neutral", pulse }: { tone?: Tone; pulse?: boolean }) {
  const c = { neutral: "bg-subtle", accent: "bg-accent", up: "bg-up", down: "bg-down", warn: "bg-warn" }[tone];
  return <span className={cn("inline-block h-1.5 w-1.5 rounded-full", c, pulse && "breathe")} aria-hidden />;
}

type BtnProps = { children: ReactNode; href?: string; onClick?: () => void; variant?: "primary" | "ghost" | "quiet"; type?: "button" | "submit";
  disabled?: boolean; className?: string; "aria-label"?: string; size?: "md" | "lg" };

export function Button({ children, href, onClick, variant = "primary", type = "button", disabled, className, size = "md", ...rest }: BtnProps) {
  const base = cn(
    "inline-flex select-none items-center justify-center gap-2 rounded-full font-medium transition duration-200 active:scale-[0.98]",
    size === "lg" ? "h-12 px-7 text-[15px]" : "h-10 px-5 text-sm",
    variant === "primary" && "bg-ink text-bg hover:bg-white",
    variant === "ghost" && "border border-line text-ink hover:border-subtle hover:bg-surface",
    variant === "quiet" && "text-muted hover:text-ink",
    disabled && "pointer-events-none opacity-40",
    className,
  );
  if (href) return <Link href={href} className={base} aria-label={rest["aria-label"]}>{children}</Link>;
  return <button type={type} onClick={onClick} disabled={disabled} className={base} aria-label={rest["aria-label"]}>{children}</button>;
}

export function Card({ children, className, as: Tag = "div" }: { children: ReactNode; className?: string; as?: "div" | "section" | "article" }) {
  return <Tag className={cn("surface", className)}>{children}</Tag>;
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "up" | "down" | "warn" | "accent" }) {
  const c = tone ? { up: "text-up", down: "text-down", warn: "text-warn", accent: "text-accent" }[tone] : "text-ink";
  const words = typeof value === "string" && /[A-Za-z]{4,}/.test(value);      // numbers use the mono face, words do not
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <p className={cn("mt-2 font-medium leading-none", words ? "text-2xl leading-tight tracking-tight sm:text-[1.65rem]" : "num text-3xl sm:text-[2rem]", c)}>{value}</p>
      {hint && <p className="mt-2 text-[13px] leading-snug text-muted">{hint}</p>}
    </div>
  );
}

export function SectionHeading({ eyebrow, title, lead, className }: { eyebrow?: string; title: ReactNode; lead?: ReactNode; className?: string }) {
  return (
    <div className={cn("max-w-2xl", className)}>
      {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
      <h2 className="h2 text-ink">{title}</h2>
      {lead && <p className="lead mt-3">{lead}</p>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function EmptyState({ title, body, action, icon }: { title: string; body?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
      <span className="grid h-11 w-11 place-items-center rounded-full border border-line text-muted">{icon ?? <Inbox className="h-5 w-5" />}</span>
      <p className="h3">{title}</p>
      {body && <p className="max-w-md text-sm leading-relaxed text-muted">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ title = "Something didn't load", body, onRetry }: { title?: string; body?: ReactNode; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="grid h-11 w-11 place-items-center rounded-full border border-down/30 bg-down/10 text-down"><AlertTriangle className="h-5 w-5" /></span>
      <p className="h3">{title}</p>
      {body && <p className="max-w-md text-sm leading-relaxed text-muted">{body}</p>}
      {onRetry && <Button variant="ghost" onClick={onRetry}><RotateCw className="h-3.5 w-3.5" /> Try again</Button>}
    </div>
  );
}

/** Progressive disclosure: native <details> keeps it keyboard- and screen-reader-friendly. */
export function Disclosure({ summary, children, className, defaultOpen }: { summary: ReactNode; children: ReactNode; className?: string; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className={cn("group", className)}>
      <summary className="flex items-center gap-2 py-1 text-[13px] font-medium text-muted transition hover:text-ink">
        {summary}
        <ChevronDown className="chev h-3.5 w-3.5 transition-transform duration-200" aria-hidden />
      </summary>
      <div className="pt-3">{children}</div>
    </details>
  );
}

export function Kv({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-6 gap-y-1 border-b border-line-soft py-3 text-sm last:border-0 sm:grid-cols-[9.5rem_1fr]">
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 leading-relaxed text-ink-2">{children}</dd>
    </div>
  );
}
