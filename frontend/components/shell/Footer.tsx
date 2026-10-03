import Link from "next/link";
import { Logo } from "@/components/shell/Nav";

export default function Footer() {
  return (
    <footer className="mt-32 border-t border-line/70">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-5 py-12 sm:px-8 md:flex-row md:items-start md:justify-between">
        <div className="max-w-sm">
          <Logo />
          <p className="mt-4 text-[13px] leading-relaxed text-muted">
            Financial intelligence that shows its work. Historical and live data, measured in Python, explained in plain language.
            Descriptive analysis, not investment advice.
          </p>
        </div>
        <ul className="grid grid-cols-2 gap-x-12 gap-y-2.5 text-[13px] text-muted sm:grid-cols-3">
          {[["Overview", "/"], ["Ask", "/ask"], ["How it works", "/intelligence"], ["Portfolio", "/portfolio"], ["History", "/history"], ["About", "/about"]].map(([l, h]) => (
            <li key={h}><Link href={h} className="transition hover:text-ink">{l}</Link></li>
          ))}
        </ul>
      </div>
    </footer>
  );
}
