import { AlertCircle, Check, ChevronUp, Copy, Info, Search, TriangleAlert, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { levelOf, type LogEntry, type LogLevel, type RunView } from "../model";
import { roleLabel } from "../roles";
import { Collapse, cx } from "../ui/bits";

const LEVELS: Array<{ id: LogLevel | "all"; label: string }> = [{ id: "all", label: "All" }, { id: "info", label: "Info" }, { id: "warn", label: "Warnings" }, { id: "error", label: "Errors" }];
const LEVEL_UI = {
  info: { icon: Info, text: "text-fg-3", label: "info" },
  warn: { icon: TriangleAlert, text: "text-blocked", label: "warn" },
  error: { icon: AlertCircle, text: "text-escalated", label: "error" },
} as const;
const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

interface Props {
  view: RunView;
  open: boolean;
  onToggle: () => void;
  taskFilter: string;
  onTaskFilter: (id: string) => void;
}

/** The event log as a collapsible bottom drawer: collapsed to one line; opened with level filters, search, a live tail,
 * copy, and monospace rows with timestamps. This is the only place with raw detail. */
export function EventLogDrawer({ view, open, onToggle, taskFilter, onTaskFilter }: Props) {
  const [level, setLevel] = useState<LogLevel | "all">("all");
  const [query, setQuery] = useState("");
  const [tail, setTail] = useState(true);
  const [copied, setCopied] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const t0 = view.startedAt || view.log[0]?.ts || 0;
  const entries = useMemo(() => {
    const q = query.trim().toLowerCase();
    return view.log.filter((e: LogEntry) => (level === "all" || levelOf(e) === level) && (!taskFilter || e.taskId === taskFilter) && (!q || e.text.toLowerCase().includes(q) || e.group.includes(q)));
  }, [view.log, level, taskFilter, query]);
  useEffect(() => {
    if (open && tail) list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [open, tail, entries.length]);
  const last = view.log[view.log.length - 1];
  const filtered = view.tasks.find((t) => t.id === taskFilter);

  const copy = async () => {
    const text = entries.map((e) => `${clock(e.ts)}  ${LEVEL_UI[levelOf(e)].label.padEnd(5)} ${e.group.padEnd(5)} ${e.text}`).join("\n");
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ }
  };

  return (
    <section aria-label="Event log" className="glass border-t border-hairline">
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls="event-log-body" className="flex h-11 w-full items-center gap-3 px-4 text-left hover:bg-raised/60">
        <ChevronUp size={16} aria-hidden className={cx("text-fg-3 transition-transform duration-200", open && "rotate-180")} />
        <span className="font-medium">Event log</span>
        <span className="rounded-full bg-raised px-2 text-[13px] tabular-nums text-fg-2">{view.log.length}</span>
        {!open && last && <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg-3">{last.text}</span>}
      </button>
      <Collapse open={open}>
        <div id="event-log-body" className="border-t border-hairline">
          <div className="flex flex-wrap items-center gap-2 px-4 py-3">
            <div role="group" aria-label="Filter by level" className="flex rounded-xl bg-raised p-1">
              {LEVELS.map((l) => (
                <button key={l.id} type="button" aria-pressed={level === l.id} onClick={() => setLevel(l.id)} className={cx("h-7 rounded-lg px-3 text-[13px] font-medium transition-colors", level === l.id ? "bg-overlay text-fg shadow-[inset_0_1px_0_var(--highlight)]" : "text-fg-3 hover:text-fg-2")}>{l.label}</button>
              ))}
            </div>
            <label className="relative min-w-[160px] flex-1 sm:max-w-[280px]">
              <span className="sr-only">Search the log</span>
              <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-3" />
              <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the log" className="h-9 w-full rounded-xl border border-control bg-page pl-8 pr-3 text-[13px] text-fg placeholder:text-fg-3" />
            </label>
            {filtered && (
              <button type="button" onClick={() => onTaskFilter("")} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-running-bg px-3 text-[13px] font-medium text-running" aria-label={`Showing ${roleLabel(filtered.role)} only. Clear this filter.`}>
                {roleLabel(filtered.role)} · try {filtered.attempt}<X size={13} aria-hidden />
              </button>
            )}
            <div className="ml-auto flex items-center gap-2">
              <button type="button" role="switch" aria-checked={tail} onClick={() => setTail(!tail)} className="inline-flex h-8 items-center gap-2 rounded-lg px-2 text-[13px] text-fg-2 hover:text-fg">
                <span aria-hidden="true" className={cx("relative h-5 w-9 rounded-full transition-colors", tail ? "bg-[var(--accent-to)]" : "bg-line")}><span className={cx("absolute top-0.5 size-4 rounded-full bg-white transition-all", tail ? "left-[18px]" : "left-0.5")} /></span>
                Live tail
              </button>
              <button type="button" onClick={copy} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-hairline bg-raised px-3 text-[13px] text-fg-2 hover:text-fg">
                {copied ? <Check size={14} aria-hidden className="text-passed" /> : <Copy size={14} aria-hidden />}{copied ? "Copied" : "Copy"}
                <span className="sr-only" aria-live="polite">{copied ? "Log copied" : ""}</span>
              </button>
            </div>
          </div>
          <div ref={list} role="log" aria-label="Events" tabIndex={0} className="h-[30vh] min-h-40 overflow-y-auto px-4 pb-3 font-mono text-[13px] leading-6">
            {entries.length === 0 && <p className="text-fg-3">No events match these filters.</p>}
            {entries.map((e) => {
              const lv = LEVEL_UI[levelOf(e)];
              return (
                <p key={e.seq} className={cx("flex items-start gap-3 rounded-md px-1 hover:bg-raised/60", levelOf(e) === "error" ? "text-escalated" : levelOf(e) === "warn" ? "text-blocked" : "text-fg-2")}>
                  <span className="w-[68px] shrink-0 text-fg-3" title={`+${Math.max(0, Math.round(e.ts - t0))}s`}>{clock(e.ts)}</span>
                  <span className={cx("inline-flex h-6 w-[64px] shrink-0 items-center gap-1", lv.text)}><lv.icon size={12} aria-hidden />{lv.label}</span>
                  <span className="hidden w-12 shrink-0 text-fg-3 sm:inline">{e.group}</span>
                  <span className="min-w-0 break-words">{e.text}</span>
                </p>
              );
            })}
          </div>
        </div>
      </Collapse>
    </section>
  );
}
