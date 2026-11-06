import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { MOTION } from "../theme/tokens";
import { cx } from "./bits";

export interface TabSpec<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  badge?: string | number;
}

export const tabId = (group: string, id: string) => `${group}-tab-${id}`;
export const panelId = (group: string, id: string) => `${group}-panel-${id}`;

/** An ARIA tablist: arrow keys, Home and End move between tabs; the selected tab has a sliding underline. */
export function Tabs<T extends string>({ group, label, tabs, value, onChange, fill = false }: { group: string; label: string; tabs: TabSpec<T>[]; value: T; onChange: (id: T) => void; fill?: boolean }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === value);
    const next = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className="flex gap-1 border-b border-hairline">
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button
            key={t.id} ref={(el) => { refs.current[t.id] = el; }} role="tab" type="button" id={tabId(group, t.id)} aria-selected={on} aria-controls={panelId(group, t.id)} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cx("relative inline-flex items-center justify-center text-sm font-medium transition-colors", fill ? "h-14 min-w-0 flex-1 flex-col gap-0.5 px-1 text-[13px]" : "h-11 gap-2 px-2.5 xl:px-3", on ? "text-fg" : "text-fg-3 hover:text-fg-2")}
          >
            {t.icon && <t.icon size={16} aria-hidden className={fill ? "" : "hidden xl:block"} />}
            <span>{t.label}</span>
            {t.badge !== undefined && <span className="rounded-full bg-raised px-1.5 text-[13px] tabular-nums text-fg-2">{t.badge}</span>}
            {on && <motion.span layoutId={`${group}-underline`} transition={MOTION.spring} className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-[var(--accent-from)] to-[var(--accent-to)]" />}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ group, id, active, children, className }: { group: string; id: string; active: boolean; children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" id={panelId(group, id)} aria-labelledby={tabId(group, id)} hidden={!active} tabIndex={0} className={cx("outline-none", className)}>
      {active && children}
    </div>
  );
}
