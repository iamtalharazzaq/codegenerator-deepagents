import { motion } from "framer-motion";
import { MessageCircleMore, PanelLeftClose, PanelLeftOpen, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { ChatRow, RunRow } from "../api";
import { groupOf, relativeTime, runTitle, runUi, RUN_LABEL, type RunGroup, type RunStatus } from "../model";
import { STATUS } from "../theme/tokens";
import { Button, cx, Skeleton, Tooltip } from "../ui/bits";
import { StatusIcon } from "../ui/StatusChip";

const GROUPS: RunGroup[] = ["Today", "Yesterday", "Earlier"];

interface Props {
  runs: RunRow[] | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  chats?: ChatRow[];
  activeChat?: string | null;
  onOpenChat?: (id: string) => void;
  /** icon-only rail (desktop) or the full list (desktop expanded, or inside the drawer on small screens) */
  collapsed: boolean;
  onToggle?: () => void;
}

function RunItem({ run, active, collapsed, onSelect }: { run: RunRow; active: boolean; collapsed: boolean; onSelect: () => void }) {
  const ui = runUi(run.status as RunStatus);
  const title = runTitle(run.request, run.run_id);
  const label = RUN_LABEL[run.status as RunStatus] ?? run.status;
  return (
    <li className="relative">
      <Tooltip label={<><span className="block font-medium">{title}</span><span className="mt-1 block text-fg-3">{label}{run.tasks_total > 0 ? ` · ${run.tasks_done}/${run.tasks_total} tasks` : ""}</span></>}>
        <button
          type="button" onClick={onSelect} aria-current={active ? "true" : undefined} aria-label={`${title}. ${label}${run.tasks_total > 0 ? `, ${run.tasks_done} of ${run.tasks_total} tasks` : ""}`}
          className={cx("relative flex w-full min-w-0 items-center gap-3 rounded-xl text-left transition-colors", collapsed ? "justify-center p-2.5" : "px-3 py-2", active ? "bg-raised" : "hover:bg-raised/60")}
        >
          {active && <motion.span layoutId="run-accent" transition={{ type: "spring", stiffness: 500, damping: 40 }} aria-hidden="true" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-gradient-to-b from-[var(--accent-from)] to-[var(--accent-to)]" />}
          <span className={STATUS[ui].text}><StatusIcon status={ui} size={collapsed ? 20 : 16} /></span>
          {!collapsed && (
            <span className="min-w-0 flex-1">
              <span className={cx("block truncate text-sm", active ? "font-medium text-fg" : "text-fg")}>{title}</span>
              <span className="mt-0.5 flex items-center gap-2 text-[13px] text-fg-3">
                <span>{relativeTime(run.created_at)}</span>
                {run.tasks_total > 0 && <><span aria-hidden="true">·</span><span className="tabular-nums">{run.tasks_done}/{run.tasks_total}</span></>}
              </span>
            </span>
          )}
        </button>
      </Tooltip>
    </li>
  );
}

/** Runs grouped by Today / Yesterday / Earlier, one truncated line each; the full prompt is in the tooltip. Collapses to icons. */
export function Sidebar({ runs, selected, onSelect, onNew, chats = [], activeChat = null, onOpenChat, collapsed, onToggle }: Props) {
  const [query, setQuery] = useState("");
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (runs ?? []).filter((r) => !q || r.request.toLowerCase().includes(q) || r.run_id.includes(q));
    return GROUPS.map((g) => ({ name: g, runs: list.filter((r) => groupOf(r.created_at) === g) })).filter((g) => g.runs.length);
  }, [runs, query]);

  return (
    <nav aria-label="Runs" className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className={cx("flex items-center gap-2", collapsed && "flex-col")}>
        {collapsed
          ? <Tooltip label="New run"><Button variant="primary" size="icon" onClick={onNew} aria-label="New run"><Plus size={18} aria-hidden /></Button></Tooltip>
          : <Button variant="primary" onClick={onNew} className="flex-1"><Plus size={16} aria-hidden />New run</Button>}
        {onToggle && (
          <Tooltip label={collapsed ? "Expand runs" : "Collapse to icons"}>
            <Button variant="ghost" size="icon" onClick={onToggle} aria-label={collapsed ? "Expand runs" : "Collapse runs"} aria-expanded={!collapsed}>
              {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
            </Button>
          </Tooltip>
        )}
      </div>
      {!collapsed && (
        <label className="relative block">
          <span className="sr-only">Search runs</span>
          <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-3" />
          <input
            type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search runs"
            className="h-10 w-full rounded-xl border border-control bg-page pl-9 pr-3 text-sm text-fg placeholder:text-fg-3"
          />
        </label>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {runs === null && (
          <div className="space-y-2" aria-busy="true" aria-label="Loading runs">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className={collapsed ? "mx-auto size-10" : "h-12"} />)}
          </div>
        )}
        {runs !== null && grouped.length === 0 && !collapsed && <p className="px-2 py-4 text-fg-3">{query ? "No runs match your search." : "No runs yet. Start one to see it here."}</p>}
        {!collapsed && chats.length > 0 && (
          <section aria-label="Conversations" className="mb-3">
            <h2 className="px-3 pb-1 pt-2 text-[13px] font-medium text-fg-3">Conversations</h2>
            <ul className="space-y-0.5">
              {chats.slice(0, 8).map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => onOpenChat?.(c.id)} aria-current={c.id === activeChat ? "true" : undefined}
                    className={cx("flex w-full min-w-0 items-center gap-3 rounded-xl px-3 py-2 text-left", c.id === activeChat ? "bg-raised" : "hover:bg-raised/60")}>
                    <MessageCircleMore size={16} aria-hidden className="shrink-0 text-fg-3" />
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm">{c.title}</span><span className="text-[13px] text-fg-3">{relativeTime(c.updated_at)}{c.runs > 0 ? ` · ${c.runs} run${c.runs > 1 ? "s" : ""}` : ""}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {grouped.map((g) => (
          <section key={g.name} aria-label={g.name} className="mb-3">
            {!collapsed && <h2 className="px-3 pb-1 pt-2 text-[13px] font-medium text-fg-3">{g.name}</h2>}
            {collapsed && <hr className="mx-3 my-2 border-hairline" />}
            <ul className="space-y-0.5">
              {g.runs.map((r) => <RunItem key={r.run_id} run={r} active={r.run_id === selected} collapsed={collapsed} onSelect={() => onSelect(r.run_id)} />)}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
