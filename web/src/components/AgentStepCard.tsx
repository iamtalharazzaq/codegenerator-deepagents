import { motion } from "framer-motion";
import { ChevronDown, Flag, ScrollText } from "lucide-react";
import { useState } from "react";

import { useData } from "../data";
import { formatDuration, guardrailText, repeatsEarlier, taskUi, type RunView, type TaskView } from "../model";
import { agentToken, MOTION, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Clamp, Collapse, cx, useNow } from "../ui/bits";
import { Markdown } from "../ui/Markdown";
import { StatusChip } from "../ui/StatusChip";

interface Props {
  view: RunView;
  task: TaskView;
  lit: boolean;
  onLogs: (taskId: string) => void;
  onOpenAgent: (role: string) => void;
}

/** One delegation as one compact card that updates in place. Identity (avatar, name, hue), state, try, time, a 2-line
 * summary, and the guardrail badges for this step. Everything else is one click away under "Details". */
export function AgentStepCard({ view, task, lit, onLogs, onOpenAgent }: Props) {
  const ui = taskUi(view, task);
  const agent = agentToken(task.role);
  const source = useData();
  const now = useNow(ui === "running");
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const seconds = (task.endTs ?? now) - task.startTs;
  const same = repeatsEarlier(view, task);
  const tool = task.toolLines[task.toolLines.length - 1];
  const failed = task.status === "fail";
  const hits = task.guardrails.length;

  const showResult = () => {
    if (!view.runId) return;
    source.artifact(view.runId, `${task.id}.attempt${task.attempt}.md`).then(setResult).catch(() => setResult("The result file is not available."));
  };

  return (
    <motion.article
      id={`task-${task.id}`} layout="position" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={MOTION.base}
      aria-label={`${agent.label}, try ${task.attempt}, ${STATUS[ui].label}`}
      className={cx("raised relative p-4", ui === "running" && "border-running/40 shadow-[0_0_0_1px_var(--running),0_8px_32px_-12px_var(--running)]", (ui === "escalated" || ui === "failed") && STATUS[ui].ring, lit && "ring-2 ring-[var(--accent)]")}
    >
      <header className="flex items-center gap-3">
        <AgentAvatar role={task.role} live={ui === "running"} />
        <div className="min-w-0 flex-1">
          <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <button type="button" onClick={() => onOpenAgent(task.role)} className="rounded-md font-semibold tracking-tight hover:underline" aria-label={`${agent.label}: open details`}>{agent.label}</button>
            <StatusChip status={ui} size="sm" />
          </h3>
          <p className="text-[13px] text-fg-3"><span>Try {task.attempt}</span> · <span className="tabular-nums">{formatDuration(seconds)}</span></p>
        </div>
      </header>

      <div className="mt-3">
        {failed && same ? (
          <p className="text-fg-2">Same error as try {same}.</p>
        ) : (
          <Clamp lines={2} className="text-fg-2"><p className="break-words">{failed && task.reason ? task.reason : task.objective}</p></Clamp>
        )}
        {failed && task.reason && <p className="mt-1 truncate text-[13px] text-fg-3" title={task.objective}>Task: {task.objective}</p>}
      </div>

      {ui === "running" && tool && <p className="mt-2 truncate rounded-lg bg-page px-2.5 py-1.5 font-mono text-[13px] text-running" title={tool}>{tool}</p>}

      {hits > 0 && (
        <button type="button" onClick={() => setOpen(true)} aria-label={`${hits} guardrail ${hits > 1 ? "hits" : "hit"}. Show details.`}
          className="mt-3 inline-flex h-7 items-center gap-1.5 rounded-full bg-blocked-bg px-2.5 text-[13px] font-medium text-blocked transition-[filter] hover:brightness-110">
          <Flag size={13} aria-hidden />{hits} guardrail {hits > 1 ? "hits" : "hit"}
        </button>
      )}

      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-3 flex items-center gap-1 text-[13px] font-medium text-accent">
        Details <ChevronDown size={14} aria-hidden className={cx("transition-transform duration-200", open && "rotate-180")} />
      </button>
      <Collapse open={open}>
        <div className="space-y-3 pt-3 text-[13px]">
          {task.writes.length > 0 && <p className="text-fg-3">May write: <span className="font-mono text-fg-2">{task.writes.join(", ")}</span></p>}
          {task.guardrails.map((g) => <p key={g.seq} className="rounded-lg bg-blocked-bg px-3 py-2 text-blocked">{guardrailText(g)}</p>)}
          {task.toolLines.length > 0 && <pre className="whitespace-pre-wrap break-words rounded-xl bg-page p-3 font-mono text-fg-2">{task.toolLines.join("\n")}</pre>}
          <div className="flex flex-wrap gap-4">
            {view.runId && task.status !== "in_progress" && <button type="button" onClick={showResult} className="font-medium text-accent hover:underline">Show result</button>}
            <button type="button" onClick={() => onLogs(task.id)} className="inline-flex items-center gap-1 font-medium text-accent hover:underline"><ScrollText size={13} aria-hidden />View in log</button>
          </div>
          {result && <div className="rounded-xl bg-page p-3"><Markdown text={result} /></div>}
        </div>
      </Collapse>
    </motion.article>
  );
}
