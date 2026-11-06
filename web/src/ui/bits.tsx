import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, Copy } from "lucide-react";
import {
  cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactElement, type ReactNode,
} from "react";

import { MOTION } from "../theme/tokens";

export { useReducedMotion };

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const SIZING = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-sm", lg: "h-11 px-5 text-[15px]", icon: "size-10 text-sm" };
const VARIANTS: Record<Variant, string> = {
  primary: "btn-primary font-semibold border border-transparent",
  secondary: "bg-raised text-fg border border-hairline hover:bg-overlay shadow-[inset_0_1px_0_var(--highlight)]",
  ghost: "bg-transparent text-fg-2 border border-transparent hover:bg-raised hover:text-fg",
  danger: "bg-escalated-bg text-escalated border border-escalated/30 hover:brightness-110",
};

export function Button({ variant = "secondary", size = "md", className, type = "button", ...rest }: { variant?: Variant; size?: "sm" | "md" | "lg" | "icon" } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const sizing = SIZING[size];
  return <button type={type} className={cx("inline-flex shrink-0 items-center justify-center gap-2 rounded-xl font-medium transition-[filter,background-color] duration-150 disabled:cursor-not-allowed", sizing, VARIANTS[variant], className)} {...rest} />;
}

/** The same look for a link that downloads, so a link and a button are never two different designs. */
export const buttonClass = (variant: Variant = "primary", size: keyof typeof SIZING = "md") =>
  cx("inline-flex shrink-0 items-center justify-center gap-2 rounded-xl font-medium transition-[filter,background-color] duration-150", SIZING[size], VARIANTS[variant]);

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
    <button type="button" onClick={copy} aria-label={`${label}: ${text}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-hairline bg-raised px-2.5 font-mono text-[13px] text-fg-2 transition-colors hover:text-fg">
      {done ? <Check size={14} aria-hidden className="text-passed" /> : <Copy size={14} aria-hidden />}
      <span>{text}</span>
      <span className="sr-only" aria-live="polite">{done ? "Copied" : ""}</span>
    </button>
  );
}

/** Long text collapsed to a few lines with "Show more". The button only appears when there is more to show. */
export function Clamp({ children, lines = 2, className }: { children: ReactNode; lines?: 1 | 2 | 3 | 4; className?: string }) {
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

/** Height-animated disclosure. Content is unmounted when closed, so hidden controls are never tabbable. */
export function Collapse({ open, children }: { open: boolean; children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
          transition={MOTION.base} style={{ overflow: "hidden" }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div aria-hidden="true" style={style} className={cx("relative animate-pulse rounded-lg bg-raised motion-reduce:animate-none", className)} />;
}

/** A pulsing dot for "something is working right now". The dot carries no meaning alone: it sits next to a word. */
export function LiveDot({ className = "bg-running" }: { className?: string }) {
  return (
    <span aria-hidden="true" className="relative inline-flex size-2 shrink-0">
      <span className={cx("ping-soft absolute inset-0 rounded-full", className)} />
      <span className={cx("relative size-2 rounded-full", className)} />
    </span>
  );
}

/** A labelled meter. The numbers are always printed, so the colour is never the only signal. */
export function Meter({ label, value, max, text, fill = "bg-running" }: { label: string; value: number; max: number; text: string; fill?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="min-w-[96px]">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-fg-3">{label}</span>
        <span className="font-semibold tabular-nums text-fg">{text}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-raised" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-valuetext={text}>
        <motion.div className={cx("h-full rounded-full", fill)} initial={false} animate={{ width: `${pct}%` }} transition={MOTION.base} />
      </div>
    </div>
  );
}

/** A tooltip that follows keyboard focus as well as the pointer. It is fixed-positioned, so scroll areas never clip it. */
export function Tooltip({ label, children, side = "right" }: { label: ReactNode; children: ReactElement<{ "aria-describedby"?: string }>; side?: "right" | "bottom" | "top" }) {
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const show = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const r = ref.current?.getBoundingClientRect();
      if (r) setAt(side === "right" ? { x: r.right + 10, y: r.top + r.height / 2 } : { x: r.left + r.width / 2, y: side === "top" ? r.top - 8 : r.bottom + 8 });
    }, 350);
  };
  const hide = () => { clearTimeout(timer.current); setAt(null); };
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); clearTimeout(timer.current); };
  }, []);
  const transform = side === "right" ? "translateY(-50%)" : side === "top" ? "translate(-50%, -100%)" : "translateX(-50%)";
  return (
    <span ref={ref} className="flex min-w-0" onMouseEnter={show} onMouseLeave={hide} onFocusCapture={show} onBlurCapture={hide}>
      {cloneElement(children, { "aria-describedby": at ? id : undefined })}
      {at && (
        <span id={id} role="tooltip" style={{ position: "fixed", left: at.x, top: at.y, transform, zIndex: 60 }}
          className="overlay pointer-events-none max-w-[320px] rounded-xl px-3 py-2 text-[13px] leading-5 text-fg">
          {label}
        </span>
      )}
    </span>
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
