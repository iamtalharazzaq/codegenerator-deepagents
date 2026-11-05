import type { RunRow } from "../api";
import type { RunStatus } from "../model";
import { Button } from "../ui/bits";
import { RunStatusChip } from "../ui/Status";

export function RunList({ runs, selected, onSelect, onNew }: { runs: RunRow[]; selected: string | null; onSelect: (id: string) => void; onNew: () => void }) {
  return (
    <nav aria-label="Runs" className="flex min-h-0 flex-col gap-2 overflow-y-auto rounded-xl border border-line bg-surface p-3">
      <Button variant="primary" onClick={onNew} className="w-full">New run</Button>
      <h2 className="mt-2 text-[13px] font-semibold uppercase tracking-wide text-fg-2">Runs</h2>
      {runs.length === 0 && <p className="text-fg-2">No runs yet.</p>}
      <ul className="space-y-1">
        {runs.map((r) => (
          <li key={r.run_id}>
            <button type="button" aria-current={r.run_id === selected ? "true" : undefined} onClick={() => onSelect(r.run_id)}
              className={`w-full rounded-lg border p-2 text-left ${r.run_id === selected ? "border-accent/60 bg-raised" : "border-transparent hover:bg-raised"}`}>
              <span className="line-clamp-2 block">{r.request || r.run_id}</span>
              <span className="mt-1.5 flex flex-wrap items-center gap-2">
                <RunStatusChip status={r.status as RunStatus} size="sm" />
                {r.tasks_total > 0 && <span className="text-[13px] tabular-nums text-fg-2">{r.tasks_done}/{r.tasks_total}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
