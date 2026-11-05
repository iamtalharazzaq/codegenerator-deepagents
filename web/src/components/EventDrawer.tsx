import { useEffect, useMemo, useRef, useState } from "react";

import type { LogEntry, RunView } from "../model";
import { roleLabel } from "../roles";

const GROUPS: { id: LogEntry["group"] | "all"; label: string }[] = [
  { id: "all", label: "All" }, { id: "task", label: "Tasks" }, { id: "tool", label: "Tools" }, { id: "guard", label: "Guardrails" }, { id: "plan", label: "Plan" }, { id: "run", label: "Run" },
];
const TAG: Record<LogEntry["group"], string> = { task: "text-running", tool: "text-fg-3", guard: "text-blocked", plan: "text-accent", run: "text-fg-2" };

/** The event log as a bottom drawer: collapsed to one line, opened with filters and a live tail. */
export function EventDrawer({ view, open, onToggle, taskFilter, onTaskFilter }: { view: RunView; open: boolean; onToggle: () => void; taskFilter: string; onTaskFilter: (id: string) => void }) {
  const [group, setGroup] = useState<LogEntry["group"] | "all">("all");
  const [tail, setTail] = useState(true);
  const list = useRef<HTMLDivElement>(null);
  const t0 = view.startedAt || view.log[0]?.ts || 0;
  const entries = useMemo(
    () => view.log.filter((e) => (group === "all" || e.group === group) && (!taskFilter || e.taskId === taskFilter)),
    [view.log, group, taskFilter],
  );
  useEffect(() => {
    if (open && tail) list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [open, tail, entries.length]);
  const last = view.log[view.log.length - 1];
  return (
    <section aria-label="Event log" className="border-t border-line bg-surface">
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls="event-log-body" className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-raised">
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={open ? "" : "rotate-180"}><path d="M3 6l5 5 5-5" /></svg>
        <span className="font-medium">Event log</span>
        <span className="text-[13px] text-fg-2">{view.log.length} events</span>
        {!open && last && <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg-3">{last.text}</span>}
      </button>
      {open && (
        <div id="event-log-body" className="border-t border-line">
          <div className="flex flex-wrap items-center gap-2 px-4 py-2">
            <div role="group" aria-label="Filter by kind" className="flex flex-wrap gap-1">
              {GROUPS.map((g) => (
                <button key={g.id} type="button" aria-pressed={group === g.id} onClick={() => setGroup(g.id)} className={`rounded-md border px-2 py-0.5 text-[13px] ${group === g.id ? "border-accent bg-accent-bg text-on-accent" : "border-control text-fg-2 hover:bg-raised"}`}>{g.label}</button>
              ))}
            </div>
            <label className="inline-flex items-center gap-2 text-[13px] text-fg-2">Task
              <select value={taskFilter} onChange={(e) => onTaskFilter(e.target.value)} className="rounded-md border border-control bg-page px-1.5 py-0.5 text-fg">
                <option value="">All tasks</option>
                {view.tasks.map((t) => <option key={t.id} value={t.id}>{roleLabel(t.role)} · try {t.attempt}</option>)}
              </select>
            </label>
            <label className="ml-auto inline-flex items-center gap-2 text-[13px] text-fg-2"><input type="checkbox" checked={tail} onChange={(e) => setTail(e.target.checked)} />Live tail</label>
          </div>
          <div ref={list} role="log" aria-label="Events" tabIndex={0} className="h-[30vh] overflow-y-auto px-4 pb-3 font-mono text-[13px] leading-relaxed">
            {entries.length === 0 && <p className="text-fg-3">No events match these filters.</p>}
            {entries.map((e) => (
              <p key={e.seq} className={`flex gap-3 ${e.error ? "text-escalated" : "text-fg-2"}`}>
                <span className="w-14 shrink-0 text-right text-fg-3">+{Math.max(0, Math.round(e.ts - t0))}s</span>
                <span className={`w-20 shrink-0 ${TAG[e.group]}`}>{e.group}</span>
                <span className="min-w-0 break-words">{e.text}</span>
              </p>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
