import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { MOTION } from "../theme/tokens";
import { cx, useReducedMotion } from "./bits";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A modal side drawer: focus moves in, Tab stays inside, Escape and the backdrop close it, and focus returns to the
 * control that opened it. Used for the runs list on small screens, an agent's details, and the full report. */
export function Drawer({ open, onClose, title, subtitle, side = "right", width = "max-w-[520px]", leading, children }: {
  open: boolean; onClose: () => void; title: string; subtitle?: ReactNode; side?: "left" | "right"; width?: string; leading?: ReactNode; children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus() ?? panel.current?.focus());
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => { cancelAnimationFrame(frame); document.removeEventListener("keydown", onKey, true); opener?.focus?.(); };
  }, [open, onClose]);

  const from = side === "right" ? 48 : -48;
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={MOTION.fast} onClick={onClose} aria-hidden="true" />
          <motion.div
            ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
            className={cx("overlay absolute inset-y-0 flex w-full flex-col rounded-none outline-none", width, side === "right" ? "right-0 rounded-l-[20px] border-r-0" : "left-0 rounded-r-[20px] border-l-0")}
            initial={reduce ? { opacity: 0 } : { x: from, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={reduce ? { opacity: 0 } : { x: from, opacity: 0 }} transition={MOTION.base}
          >
            <header className="flex items-start gap-3 border-b border-hairline px-5 py-4">
              {leading}
              <div className="min-w-0 flex-1">
                <h2 id={titleId} className="truncate text-[17px] font-semibold tracking-tight">{title}</h2>
                {subtitle && <div className="mt-0.5 text-[13px] text-fg-2">{subtitle}</div>}
              </div>
              <button type="button" data-autofocus onClick={onClose} aria-label={`Close ${title}`} className="grid size-9 place-items-center rounded-xl text-fg-2 hover:bg-raised hover:text-fg"><X size={18} aria-hidden /></button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
