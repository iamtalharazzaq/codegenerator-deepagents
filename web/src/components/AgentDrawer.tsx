import { Flag, ScrollText } from "lucide-react";
import { useState } from "react";

import { useData } from "../data";
import { agentUi, formatDuration, guardrailText, taskUi, type RunView, type TaskView } from "../model";
import { agentToken, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Button, Skeleton } from "../ui/bits";
import { Drawer } from "../ui/Drawer";
import { Markdown } from "../ui/Markdown";
import { StatusChip } from "../ui/StatusChip";

function TaskSection({ view, task }: { view: RunView; task: TaskView }) {
  const source = useData();
  const [output, setOutput] = useState<string | null | "loading">(null);
  const ui = taskUi(view, task);
  const seconds = task.endTs !== null ? task.endTs - task.startTs : null;
  const load = () => {
    if (!view.runId) return;
    setOutput("loading");
    source.artifact(view.runId, `${task.id}.attempt${task.attempt}.md`).then(setOutput).catch(() => setOutput("The result file is not available."));
  };
  return (
    <li className="raised p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold">Try {task.attempt}</h4>
        <StatusChip status={ui} size="sm" />
        <span className="ml-auto text-[13px] tabular-nums text-fg-3">{seconds !== null ? formatDuration(seconds) : "running"}</span>
      </div>
      <p className="mt-2 text-fg-2">{task.objective}</p>
      {task.status === "fail" && task.reason && <p className="mt-2 break-words rounded-lg bg-escalated-bg px-3 py-2 text-[13px] text-escalated">{task.reason}</p>}
      {task.writes.length > 0 && <p className="mt-2 text-[13px] text-fg-3">May write: <span className="font-mono text-fg-2">{task.writes.join(", ")}</span></p>}
      {task.guardrails.map((g) => <p key={g.seq} className="mt-2 flex items-start gap-2 rounded-lg bg-blocked-bg px-3 py-2 text-[13px] text-blocked"><Flag size={14} aria-hidden className="mt-0.5 shrink-0" />{guardrailText(g)}</p>)}
      {task.status !== "in_progress" && view.runId && output === null && <button type="button" onClick={load} className="mt-3 text-[13px] font-medium text-accent hover:underline">Show output</button>}
      {output === "loading" && <Skeleton className="mt-3 h-16" />}
      {output && output !== "loading" && <div className="mt-3 rounded-xl bg-page p-3"><Markdown text={output} /></div>}
    </li>
  );
}

/** A side drawer with everything about one agent: its tasks and tries, their output, and its slice of the event log. */
export function AgentDrawer({ view, role, onClose, onLogs }: { view: RunView; role: string | null; onClose: () => void; onLogs: (role: string) => void }) {
  const a = agentToken(role ?? "");
  const tasks = view.tasks.filter((t) => t.role === role).sort((x, y) => x.startSeq - y.startSeq);
  const ui = role ? agentUi(view, role) : "idle";
  const total = tasks.reduce((sum, t) => sum + ((t.endTs ?? t.startTs) - t.startTs), 0);
  const log = view.log.filter((e) => e.role === role).slice(-30);
  const t0 = view.startedAt || view.log[0]?.ts || 0;
  return (
    <Drawer
      open={!!role} onClose={onClose} title={a.label} leading={role ? <AgentAvatar role={role} size="lg" live={ui === "running"} /> : null}
      subtitle={<span className="flex flex-wrap items-center gap-2"><StatusChip status={ui} size="sm" /><span>{tasks.length ? `${tasks.length} ${tasks.length === 1 ? "try" : "tries"} · ${formatDuration(total)} in total` : STATUS[ui].aria}</span></span>}
    >
      {tasks.length === 0 ? (
        <p className="text-fg-2">{a.label} has not been given work in this run{ui === "blocked" || ui === "queued" ? ", but it is in the plan and waits its turn" : ""}.</p>
      ) : (
        <div className="space-y-6">
          <section aria-labelledby="drawer-tasks">
            <h3 id="drawer-tasks" className="mb-2 text-[13px] font-medium text-fg-3">Tasks and output</h3>
            <ol className="space-y-3">{tasks.map((t) => <TaskSection key={t.id} view={view} task={t} />)}</ol>
          </section>
          <section aria-labelledby="drawer-logs">
            <div className="mb-2 flex items-center justify-between">
              <h3 id="drawer-logs" className="text-[13px] font-medium text-fg-3">Logs</h3>
              <Button variant="ghost" size="sm" onClick={() => role && onLogs(role)}><ScrollText size={14} aria-hidden />Open in event log</Button>
            </div>
            <div role="log" aria-label={`${a.label} log`} className="rounded-xl bg-page p-3 font-mono text-[13px] leading-6">
              {log.map((e) => (
                <p key={e.seq} className={e.error ? "text-escalated" : "text-fg-2"}><span className="mr-3 text-fg-3">+{Math.max(0, Math.round(e.ts - t0))}s</span>{e.text}</p>
              ))}
              {log.length === 0 && <p className="text-fg-3">Nothing logged yet.</p>}
            </div>
          </section>
        </div>
      )}
    </Drawer>
  );
}
