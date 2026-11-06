import { motion } from "framer-motion";
import { Download, Menu, Moon, RotateCcw, ScrollText, Square, Sun } from "lucide-react";

import { formatDuration, headline, isResumable, isWorking, progress, segments, type RunView, type UiStatus } from "../model";
import type { Theme } from "../theme/useTheme";
import { Button, buttonClass, cx, CopyButton, Meter, useNow } from "../ui/bits";
import { StatusChip } from "../ui/StatusChip";

const SEGMENT: Record<UiStatus, string> = {
  passed: "bg-passed", running: "bg-running shimmer", escalated: "bg-escalated", failed: "bg-failed", blocked: "bg-blocked/60", queued: "bg-line", idle: "bg-line",
};

/** One segment per task, coloured by state. The count is printed next to it and the bar is a progressbar for screen readers. */
function SegmentedProgress({ view }: { view: RunView }) {
  const { done, total } = progress(view);
  const parts = segments(view);
  if (!parts.length) return null;
  return (
    <div className="min-w-[140px]">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-fg-3">Tasks</span>
        <span className="font-semibold tabular-nums">{done}/{total}</span>
      </div>
      <div role="progressbar" aria-label="Tasks" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-valuetext={`${done} of ${total} tasks done`} className="mt-1 flex h-1.5 gap-[3px]">
        {parts.map((ui, i) => (
          <motion.span key={i} layout className={cx("relative h-full min-w-2 flex-1 overflow-hidden rounded-full", SEGMENT[ui])} initial={{ scaleX: 0.4, opacity: 0 }} animate={{ scaleX: 1, opacity: 1 }} transition={{ duration: 0.3, delay: i * 0.04 }} title={`Task ${i + 1}: ${ui}`} />
        ))}
      </div>
    </div>
  );
}

interface Props {
  view: RunView;
  title: string;
  demo: boolean;
  mock: boolean;
  theme: Theme;
  wide: boolean;
  logOpen: boolean;
  onToggleTheme: () => void;
  onMenu: () => void;
  onResume: () => void;
  onStop: () => void;
  onReport: () => void;
  onToggleLog: () => void;
}

/** Sticky glass header: breadcrumb, the big status pill, task segments, dispatch budget, time, run ID, and ONE primary
 * action that depends on the state (Download zip when passed, Resume run when stuck, Stop while running). */
export function TopBar({ view, title, demo, mock, theme, wide, logOpen, onToggleTheme, onMenu, onResume, onStop, onReport, onToggleLog }: Props) {
  const now = useNow(view.status === "running");
  const head = headline(view);
  const empty = view.status === "idle";
  const elapsed = view.startedAt ? (view.endedAt ?? now) - view.startedAt : 0;
  const used = view.dispatches / Math.max(1, view.maxDispatches);
  const meterFill = used >= 1 ? "bg-escalated" : used >= 0.75 ? "bg-blocked" : "bg-running";

  let cta: React.ReactNode = null;
  if (view.status === "passed" && view.zip && view.runId) {
    cta = <a href={`/api/runs/${view.runId}/delivery.zip`} download className={buttonClass("primary")}><Download size={16} aria-hidden />Download zip</a>;
  } else if (view.status === "passed") {
    cta = <Button variant="secondary" onClick={onReport}><ScrollText size={16} aria-hidden />Full report</Button>;
  } else if (isResumable(view.status)) {
    cta = <Button variant="primary" onClick={onResume}><RotateCcw size={16} aria-hidden />Resume run</Button>;
  } else if (view.status === "running") {
    cta = <Button variant="danger" onClick={onStop}><Square size={14} aria-hidden fill="currentColor" />Stop</Button>;
  }

  return (
    <header className="glass sticky top-0 z-30 border-b border-hairline">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3">
        {!wide && <Button variant="ghost" size="sm" onClick={onMenu} aria-label="Open runs" className="mr-auto sm:mr-0"><Menu size={18} aria-hidden /></Button>}
        <nav aria-label="Breadcrumb" className="order-last flex min-w-0 basis-full items-center gap-2 text-[15px] sm:order-none sm:basis-0 sm:flex-1">
          <span className="text-gradient hidden shrink-0 font-semibold tracking-tight sm:inline">Orchestrator</span>
          <span aria-hidden="true" className="hidden text-fg-3 sm:inline">/</span>
          <h1 className="min-w-0 truncate font-medium" title={title} aria-current="page">{title}</h1>
        </nav>
        {demo && <span className="hidden rounded-full bg-blocked-bg px-2.5 py-1 text-[13px] font-medium text-blocked sm:inline">Demo: scripted model</span>}
        {mock && <span className="hidden rounded-full bg-running-bg px-2.5 py-1 text-[13px] font-medium text-running sm:inline">Mock data</span>}
        <Button variant="ghost" size="sm" onClick={onToggleLog} aria-pressed={logOpen} aria-label="Event log" className={logOpen ? "text-fg" : ""}><ScrollText size={16} aria-hidden /><span className="hidden md:inline">Log</span></Button>
        <Button variant="ghost" size="sm" onClick={onToggleTheme} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>{theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}</Button>
        {cta}
      </div>
      {!empty ? (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 pb-3 pt-3">
          <StatusChip status={head.ui} label={head.label} size="lg" />
          <SegmentedProgress view={view} />
          <Meter label="Delegations" value={view.dispatches} max={view.maxDispatches} text={`${view.dispatches}/${view.maxDispatches}`} fill={meterFill} />
          <div className="text-[13px]"><div className="text-fg-3">Elapsed</div><div className="font-semibold tabular-nums">{formatDuration(elapsed)}</div></div>
          {view.runId && <div className="ml-auto"><CopyButton text={view.runId} label="Copy run ID" /></div>}
        </div>
      ) : <div className="h-3" />}
      {isWorking(view) && <span aria-hidden="true" className="glow-pulse absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-[var(--accent-from)] to-transparent" />}
    </header>
  );
}
