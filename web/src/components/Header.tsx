import { formatDuration, isResumable, progress, type RunView } from "../model";
import { Button, CopyButton, Meter, useNow } from "../ui/bits";
import { RunStatusChip, StatusChip } from "../ui/Status";

/** Run status, progress, and the one primary action when the run is stuck. Each fact appears here once. */
export function Header({ view, demo, mock, onResume }: { view: RunView; demo: boolean; mock: boolean; onResume: () => void }) {
  const now = useNow(view.status === "running");
  const { done, total } = progress(view);
  const used = view.dispatches / Math.max(1, view.maxDispatches);
  const elapsed = view.startedAt ? (view.endedAt ?? now) - view.startedAt : 0;
  const empty = view.status === "idle";
  return (
    <header className="border-b border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-lg font-semibold tracking-tight">Orchestrator</h1>
        {demo && <span className="rounded-md bg-blocked-bg px-2 py-0.5 text-[13px] font-medium text-blocked">Demo: scripted model</span>}
        {mock && <span className="rounded-md bg-running-bg px-2 py-0.5 text-[13px] font-medium text-running">Mock data</span>}
        {!empty && <p className="order-last w-full truncate text-fg-2 sm:order-none sm:w-auto sm:min-w-0 sm:flex-1" title={view.request}>{view.request}</p>}
        {empty && <p className="flex-1 text-fg-3">Start a run to see its status here.</p>}
        {isResumable(view.status) && <Button variant="primary" onClick={onResume}>Resume run</Button>}
      </div>
      {!empty && (
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3">
          {view.status === "running" && (view.review || view.awaitingApproval)
            ? <StatusChip status="blocked" label="Waiting for you" size="lg" />
            : <RunStatusChip status={view.status} />}
          {total > 0 && <Meter label="Tasks" value={done} max={total} text={`${done}/${total}`} tone="passed" />}
          <p className={`text-[13px] tabular-nums ${used >= 1 ? "text-escalated" : used >= 0.75 ? "text-blocked" : "text-fg-2"}`}>{view.dispatches}/{view.maxDispatches} dispatches</p>
          <p className="text-[13px] tabular-nums text-fg-2">{formatDuration(elapsed)}</p>
          <p className="flex min-w-0 items-center gap-2 text-[13px] text-fg-2">
            {view.project && <span className="truncate font-mono" title="Project folder">{view.project}</span>}
            {view.runId && <CopyButton text={view.runId} label="Copy run ID" />}
          </p>
        </div>
      )}
    </header>
  );
}
