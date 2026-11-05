import { formatDuration, isResumable, progress, type RunView } from "../model";
import { Button, CopyButton, Meter, useNow } from "../ui/bits";
import { RunStatusChip } from "../ui/Status";

/** Run status first, then progress, then the budget. The one primary action is the next step when the run is stuck. */
export function Header({ view, demo, mock, onResume }: { view: RunView; demo: boolean; mock: boolean; onResume: () => void }) {
  const now = useNow(view.status === "running");
  const { done, total } = progress(view);
  const used = view.dispatches / Math.max(1, view.maxDispatches);
  const budgetTone = used >= 1 ? "escalated" : used >= 0.75 ? "blocked" : "running";
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
          <RunStatusChip status={view.status} />
          <Meter label="Tasks" value={done} max={Math.max(total, 1)} text={`${done}/${total}`} tone="passed" />
          <Meter label="Dispatch budget" value={view.dispatches} max={view.maxDispatches} text={`${view.dispatches}/${view.maxDispatches}`} tone={budgetTone} />
          <dl className="flex gap-6 text-[13px]">
            <div><dt className="text-fg-2">At once</dt><dd className="font-semibold tabular-nums">{view.concurrency}</dd></div>
            <div><dt className="text-fg-2">Elapsed</dt><dd className="font-semibold tabular-nums">{formatDuration(elapsed)}</dd></div>
          </dl>
          {view.runId && <CopyButton text={view.runId} label="Copy run ID" />}
        </div>
      )}
    </header>
  );
}
