import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { agentUi, formatDuration, guardrailText, latestTask, taskUi, type RunView, type TaskView } from "../model";
import { roleLabel } from "../roles";
import { Button } from "../ui/bits";
import { StatusChip } from "../ui/Status";

function TaskBlock({ view, task, onLogs }: { view: RunView; task: TaskView; onLogs: (taskId: string) => void }) {
  const [artifact, setArtifact] = useState<string | null>(null);
  const seconds = (task.endTs ?? Date.now() / 1000) - task.startTs;
  const load = () => {
    if (!view.runId) return;
    api.artifact(view.runId, `${task.id}.attempt${task.attempt}.md`).then(setArtifact).catch(() => setArtifact("The result file is not available (mock data, or the run was cleaned up)."));
  };
  return (
    <li className="rounded-lg border border-line bg-raised p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">Try {task.attempt}</span>
        <span className="flex items-center gap-2"><span className="font-mono text-[13px] text-fg-3">{formatDuration(seconds)}</span><StatusChip status={taskUi(view, task)} size="sm" /></span>
      </div>
      <p className="mt-1 text-fg-2">{task.objective}</p>
      {task.writes.length > 0 && <p className="mt-2 text-[13px] text-fg-3">May write: <span className="font-mono text-fg-2">{task.writes.join(", ")}</span></p>}
      {task.reason && <p className="mt-2 break-words font-mono text-[13px] text-fg">{task.reason}</p>}
      {task.guardrails.length > 0 && (
        <ul className="mt-2 space-y-1">
          {task.guardrails.map((g) => <li key={g.seq} className="rounded-md bg-blocked-bg px-2 py-1 text-[13px] text-blocked">{guardrailText(g)}</li>)}
        </ul>
      )}
      {task.toolLines.length > 0 && <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-page p-2 font-mono text-[13px] text-fg-2">{task.toolLines.join("\n")}</pre>}
      <div className="mt-2 flex flex-wrap gap-2">
        {view.runId && task.status !== "in_progress" && <Button variant="ghost" onClick={load}>Show result</Button>}
        <Button variant="ghost" onClick={() => onLogs(task.id)}>View logs</Button>
      </div>
      {artifact && <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-page p-2 font-mono text-[13px] text-fg-2">{artifact}</pre>}
    </li>
  );
}

/** Per-agent details in a side panel: every try, why it ended that way, what it touched. Esc closes it. */
export function AgentPanel({ view, role, onClose, onLogs }: { view: RunView; role: string; onClose: () => void; onLogs: (taskId: string) => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const on = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  const tasks = view.tasks.filter((t) => t.role === role).sort((a, b) => b.startSeq - a.startSeq);
  const last = latestTask(view.tasks, role);
  return (
    <aside role="dialog" aria-label={`Details for ${roleLabel(role)}`} className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[440px] flex-col border-l border-line bg-surface shadow-2xl">
      <div className="flex items-start justify-between gap-3 border-b border-line p-4">
        <div>
          <h2 className="text-base font-semibold">{roleLabel(role)}</h2>
          <div className="mt-1"><StatusChip status={agentUi(view, role)} /></div>
          {last && <p className="mt-2 text-[13px] text-fg-3">{tasks.length} {tasks.length === 1 ? "try" : "tries"} so far</p>}
        </div>
        <button ref={close} type="button" onClick={onClose} aria-label="Close details" className="rounded-md border border-control px-2 py-1 text-fg-2 hover:bg-raised hover:text-fg">Close</button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tasks.length === 0 ? <p className="text-fg-2">This specialist has not been given any work in this run.</p> : <ul className="space-y-3">{tasks.map((t) => <TaskBlock key={t.id} view={view} task={t} onLogs={onLogs} />)}</ul>}
      </div>
    </aside>
  );
}
