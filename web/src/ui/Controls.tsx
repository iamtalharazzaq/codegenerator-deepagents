import { ChevronDown } from "lucide-react";
import { useId, type ReactNode, type SelectHTMLAttributes } from "react";

import { cx } from "./bits";

/** An on/off setting: a real checkbox (keyboard, screen readers and form behaviour for free) drawn as a switch, in a
 * card that says what it does. The whole card is the click target. */
export function Toggle({ checked, onChange, title, hint }: { checked: boolean; onChange: (v: boolean) => void; title: string; hint: string }) {
  const hintId = useId();
  return (
    <label
      className={cx(
        "group flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors",
        checked ? "border-accent/40 bg-accent/10" : "border-hairline bg-raised hover:bg-overlay",
      )}
    >
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-describedby={hintId} className="peer sr-only" />
      <span
        aria-hidden
        className={cx(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors",
          "peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent",
          checked ? "border-transparent bg-[var(--accent-from)]" : "border-control bg-page",
        )}
      >
        <span className={cx("absolute top-0.5 size-3.5 rounded-full transition-[left,background-color] duration-150 motion-reduce:transition-none", checked ? "left-[1.1rem] bg-white" : "left-0.5 bg-fg-2")} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold text-fg">{title}</span>
        <span id={hintId} className="block text-[12px] leading-snug text-fg-2">{hint}</span>
      </span>
    </label>
  );
}

/** A dropdown with a label above it and one consistent look. It is still the browser's own select, so it works with
 * the keyboard, with screen readers and on phones; only the closed box is styled (and the list follows the dark theme). */
export function Select({ label, className, children, ...rest }: { label: string; children: ReactNode } & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className={cx("min-w-0", className)}>
      <label htmlFor={id} className="mb-1 block text-[12px] font-medium text-fg-2">{label}</label>
      <div className="relative">
        <select
          id={id}
          {...rest}
          className="h-10 w-full cursor-pointer appearance-none truncate rounded-xl border border-control bg-page pl-3 pr-9 text-[14px] text-fg transition-colors hover:bg-raised"
        >
          {children}
        </select>
        <ChevronDown size={16} aria-hidden className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-fg-2" />
      </div>
    </div>
  );
}
