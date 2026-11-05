import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { feed, formatDuration, guardrailText, repeatsEarlier, taskUi, type RunView, type TaskView } from "../model";
import { roleLabel } from "../roles";
import { Clamp } from "../ui/bits";
import { StatusIcon, STATUS } from "../ui/Status";

/** One delegation as one card that updates in place: running, then passed or failed. Everything else about it
 * (writes, tool calls, guardrail hits, the result file) is one click away in "Details", not repeated elsewhere. */
function TaskCard({ view, task, lit, onLogs }: { view: RunView; task: TaskView; lit: boolean; onLogs: (taskId: string) => void }) {
  const ui = taskUi(view, task);
  const [artifact, setArtifact] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const seconds = (task.endTs ?? Date.now() / 1000) - task.startTs;
  const same = repeatsEarlier(view, task);
  const tool = task.toolLines[task.toolLines.length - 1];
  const showResult = () => {
    if (!view.runId) return;
    api.artifact(view.runId, `${task.id}.attempt${task.attempt}.md`).then(setArtifact).catch(() => setArtifact("The result file is not available."));
  };
  return (
    <article id={`task-${task.id}`} aria-label={`${roleLabel(task.role)}, try ${task.attempt}, ${STATUS[ui].label}`}
      className={`rounded-xl border bg-raised p-3 transition-shadow ${STATUS[ui].ring} ${lit ? "ring-2 ring-accent" : ""}`}>
      <header className="flex items-start justify-between gap-3">
        <h3 className="flex items-center gap-2 font-semibold">
          <span className={STATUS[ui].text}><StatusIcon status={ui} size={18} /></span>
          {roleLabel(task.role)}
          <span className={`text-[13px] font-medium ${STATUS[ui].text}`}>{STATUS[ui].label.toLowerCase()}</span>
        </h3>
        <p className="shrink-0 text-[13px] text-fg-3"><span>try {task.attempt}</span> · <span className="font-mono">{formatDuration(seconds)}</span></p>
      </header>
      <p className="mt-1 line-clamp-2 text-fg-2">{task.objective}</p>
      {ui === "running" && tool && <p className="mt-2 truncate font-mono text-[13px] text-running" title={tool}>{tool}</p>}
      {task.status === "fail" && (
        same ? <p className="mt-2 text-[13px] text-fg-2">Same error as try {same}.</p>
          : task.reason && <Clamp lines={2} className="mt-2"><p className="break-words font-mono text-[13px] text-fg">{task.reason}</p></Clamp>
      )}
      {task.guardrails.length > 0 && (
        <button type="button" onClick={() => setOpen(true)} className="mt-2 inline-flex items-center gap-1 rounded-md bg-blocked-bg px-2 py-0.5 text-[13px] font-medium text-blocked hover:brightness-125"
          aria-label={`${task.guardrails.length} guardrail hit${task.guardrails.length > 1 ? "s" : ""}. Show details.`}>
          <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor"><path d="M3 2v12h1.5V9h8l-2-3.5 2-3.5H3z" /></svg>
          {task.guardrails.length} guardrail hit{task.guardrails.length > 1 ? "s" : ""}
        </button>
      )}
      <details className="mt-2" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="text-[13px] font-medium text-accent">Details</summary>
        <div className="mt-2 space-y-2 text-[13px]">
          {task.writes.length > 0 && <p className="text-fg-3">May write: <span className="font-mono text-fg-2">{task.writes.join(", ")}</span></p>}
          {task.guardrails.map((g) => <p key={g.seq} className="rounded-md bg-blocked-bg px-2 py-1 text-blocked">{guardrailText(g)}</p>)}
          {task.toolLines.length > 0 && <pre className="max-h-40 overflow-auto rounded-md bg-page p-2 font-mono text-fg-2">{task.toolLines.join("\n")}</pre>}
          <div className="flex flex-wrap gap-3">
            {view.runId && task.status !== "in_progress" && <button type="button" onClick={showResult} className="text-accent hover:underline">Show result</button>}
            <button type="button" onClick={() => onLogs(task.id)} className="text-accent hover:underline">View in log</button>
          </div>
          {artifact && <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-page p-2 font-mono text-fg-2">{artifact}</pre>}
        </div>
      </details>
    </article>
  );
}

/** The run as one chronological feed. Plans, the finish and the blocker are not repeated here: they have their own cards. */
export function Feed({ view, focus, onLogs }: { view: RunView; focus: { id: string; n: number } | null; onLogs: (taskId?: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const items = feed(view);
  useEffect(() => {
    const toEnd = () => box.current?.scrollTo({ top: box.current.scrollHeight });
    toEnd();
    const frame = requestAnimationFrame(toEnd);
    return () => cancelAnimationFrame(frame);
  }, [items.length, view.tasks.length]);
  useEffect(() => {
    if (focus) document.getElementById(`task-${focus.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  if (!items.length) {
    return (
      <div className="flex-1 overflow-y-auto p-4 text-fg-2">
        <p className="text-base font-semibold text-fg">What should be built?</p>
        <p className="mt-2 max-w-[48ch]">Describe the change. The Project Manager makes a plan, hands each piece to the right specialist, reads every result, and decides what comes next.</p>
      </div>
    );
  }
  return (
    <div ref={box} className="flex-1 space-y-3 overflow-y-auto p-4" tabIndex={0} aria-label="Activity">
      {items.map((it) => {
        if (it.kind === "user") return <p key={`u${it.seq}`} className="ml-auto max-w-[92%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-raised px-3 py-2">{it.text}</p>;
        if (it.kind === "note") return <p key={`n${it.seq}`} className={`rounded-lg px-3 py-2 text-[13px] ${it.tone === "warn" ? "bg-blocked-bg text-blocked" : "bg-raised text-fg-2"}`}>{it.text}</p>;
        return (
          <section key={`w${it.seq}`} aria-label={it.parallel ? `${it.tasks.length} tasks ran at the same time` : undefined}>
            {it.parallel && <h2 className="mb-1.5 text-[13px] font-semibold uppercase tracking-wide text-fg-2">{it.tasks.length} at once</h2>}
            <div className={it.parallel ? "grid gap-2 sm:grid-cols-2" : ""}>
              {it.tasks.map((t) => <TaskCard key={t.id} view={view} task={t} lit={focus?.id === t.id} onLogs={onLogs} />)}
            </div>
          </section>
        );
      })}
    </div>
  );
}
