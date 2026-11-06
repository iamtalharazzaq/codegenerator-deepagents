import { ChevronDown, History, Minus, Plus } from "lucide-react";
import { useState } from "react";

import type { RunView } from "../model";
import { Collapse, cx } from "../ui/bits";

/** Every change to the plan as a diff: added tasks in green, removed in red, and one line on why it changed. */
export function RevisionHistory({ view }: { view: RunView }) {
  const [open, setOpen] = useState(false);
  const revisions = view.todoChanges.filter((c) => c.added.length || c.removed.length);
  if (!revisions.length) return null;
  return (
    <section aria-labelledby="revisions-title" className="surface">
      <h2 id="revisions-title">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 rounded-[inherit] px-5 py-4 text-left">
          <History size={18} aria-hidden className="text-fg-3" />
          <span className="flex-1 font-semibold">Revision history</span>
          <span className="rounded-full bg-raised px-2 py-0.5 text-[13px] tabular-nums text-fg-2">{revisions.length} {revisions.length === 1 ? "replan" : "replans"}</span>
          <ChevronDown size={16} aria-hidden className={cx("text-fg-3 transition-transform duration-200", open && "rotate-180")} />
        </button>
      </h2>
      <Collapse open={open}>
        <ol className="space-y-5 border-t border-hairline px-5 py-4">
          {revisions.map((c, i) => (
            <li key={c.seq}>
              <p className="text-[13px] font-semibold text-fg-3">Revision {i + 1}</p>
              {c.why && <p className="mt-0.5 text-fg-2">{c.why}</p>}
              <ul className="mt-2 space-y-1.5" aria-label={`Changes in revision ${i + 1}`}>
                {c.removed.map((r) => (
                  <li key={`r${r}`} className="flex items-start gap-2 rounded-lg bg-escalated-bg px-3 py-2 text-[13px] text-escalated">
                    <Minus size={14} aria-label="Removed" className="mt-0.5 shrink-0" /><span className="min-w-0 break-words line-through decoration-escalated/50">{r}</span>
                  </li>
                ))}
                {c.added.map((a) => (
                  <li key={`a${a}`} className="flex items-start gap-2 rounded-lg bg-passed-bg px-3 py-2 text-[13px] text-passed">
                    <Plus size={14} aria-label="Added" className="mt-0.5 shrink-0" /><span className="min-w-0 break-words">{a}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </Collapse>
    </section>
  );
}
