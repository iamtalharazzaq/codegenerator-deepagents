import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** A labelled meter. `tone` picks the fill; the numbers are always printed so the colour is never the only signal. */
export function Meter({ label, value, max, text, tone = "running" }: { label: string; value: number; max: number; text: string; tone?: "passed" | "running" | "blocked" | "escalated" }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const fill = { passed: "bg-passed", running: "bg-running", blocked: "bg-blocked", escalated: "bg-escalated" }[tone];
  return (
    <div className="min-w-[150px]">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-fg-2">{label}</span>
        <span className="font-semibold tabular-nums text-fg">{text}</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-raised" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-valuetext={text}>
        <div className={`h-full rounded-full ${fill} transition-[width] duration-300`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setDone(true);
    setTimeout(() => setDone(false), 1600);
  };
  return (
    <button type="button" onClick={copy} aria-label={`${label}: ${text}`} className="inline-flex items-center gap-1.5 rounded-md border border-control px-2 py-1 font-mono text-[13px] text-fg-2 hover:bg-raised hover:text-fg">
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" /><path d="M10.5 5.5v-2a1.5 1.5 0 0 0-1.5-1.5h-5A1.5 1.5 0 0 0 2.5 3.5v5A1.5 1.5 0 0 0 4 10h1.5" /></svg>
      <span>{text}</span>
      <span className="sr-only" aria-live="polite">{done ? "Copied" : ""}</span>
      {done && <span aria-hidden="true" className="text-passed">Copied</span>}
    </button>
  );
}

/** Long text collapsed to three lines with "Show more". The button only appears when there is more to show. */
export function Clamp({ children, lines = 3, className = "" }: { children: ReactNode; lines?: 1 | 2 | 3 | 4; className?: string }) {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const clamp = { 1: "line-clamp-1", 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4" }[lines];
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setOverflows(el.scrollHeight > el.clientHeight + 1);
  });
  return (
    <div className={className}>
      <div ref={ref} className={open ? "" : clamp}>{children}</div>
      {(overflows || open) && (
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-1 text-[13px] font-medium text-accent underline-offset-2 hover:underline">
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => (typeof window === "undefined" ? true : window.matchMedia(query).matches));
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatches(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return matches;
}

export function Card({ children, className = "", as: Tag = "section", ...rest }: { children: ReactNode; className?: string; as?: "section" | "div" | "aside" | "header" } & React.HTMLAttributes<HTMLElement>) {
  return <Tag className={`rounded-xl border border-line bg-surface ${className}`} {...rest}>{children}</Tag>;
}

export function Button({ variant = "secondary", className = "", ...rest }: { variant?: "primary" | "secondary" | "ghost" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles = {
    primary: "bg-accent-bg text-on-accent border-transparent hover:brightness-110 font-semibold",
    secondary: "bg-raised text-fg border-control hover:bg-line/50",
    ghost: "bg-transparent text-fg-2 border-transparent hover:bg-raised hover:text-fg",
    danger: "bg-escalated-bg text-escalated border-escalated/40 hover:brightness-125",
  }[variant];
  return <button type="button" className={`inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50 ${styles} ${className}`} {...rest} />;
}
