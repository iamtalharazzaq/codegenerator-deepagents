import { motion } from "framer-motion";
import { Check, RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";

import { roleOfTodo, todoUi, triesForTodo, type RunView } from "../model";
import { agentToken, MOTION, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Button, Clamp, cx, Skeleton } from "../ui/bits";
import { StatusChip, StatusIcon } from "../ui/StatusChip";

/** "Backend Developer: build it" -> ["Backend Developer", "build it"] when the prefix names the stage's own specialist. */
function splitTodo(content: string, role: string | null): [string | null, string] {
  if (!role) return [null, content];
  const label = agentToken(role).label;
  return content.toLowerCase().startsWith(label.toLowerCase()) ? [label, content.slice(label.length).replace(/^\s*[:\-–]\s*/, "")] : [null, content];
}

/** The plan as a stage-by-stage stepper: a numbered rail, each stage's specialist, status and number of tries. It also
 * holds the Project Manager's reasoning (clamped) and the approval buttons while the plan waits for you. */
export function PlanStepper({ view, onApprove, onOpenRole, onResume, busy = false }: { view: RunView; onApprove: (approved: boolean, feedback?: string) => void; onOpenRole: (role: string) => void; onResume?: () => void; busy?: boolean }) {
  const [changes, setChanges] = useState("");
  const planning = view.status === "running" && view.todos.length === 0 && !view.awaitingApproval;
  const latest = view.pmNotes[view.pmNotes.length - 1];
  return (
    <section aria-labelledby="plan-title" className="surface p-5">
      <h2 id="plan-title" className="flex items-center gap-2 text-[17px] font-semibold tracking-tight">
        Plan
        {planning && <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-running"><StatusIcon status="running" size={14} />Project Manager is planning…</span>}
      </h2>
      {latest && (
        <div className="mt-3 flex gap-3">
          <AgentAvatar role="project_manager" size="sm" />
          <Clamp lines={3} className="min-w-0 flex-1 text-fg-2"><p className="whitespace-pre-wrap break-words">{latest.text}</p></Clamp>
        </div>
      )}
      {planning && <div className="mt-4 space-y-2" aria-hidden="true">{[78, 62, 70].map((w) => <Skeleton key={w} className="h-5" style={{ width: `${w}%` }} />)}</div>}

      {view.todos.length > 0 && (
        <ol className="mt-5" aria-label="Plan stages">
          {view.todos.map((t, i) => {
            const ui = todoUi(view, t);
            const role = roleOfTodo(t.content);
            const tries = triesForTodo(view, t);
            const [who, what] = splitTodo(t.content, role);
            const last = i === view.todos.length - 1;
            return (
              <motion.li key={t.content} layout="position" transition={MOTION.base} className="relative flex gap-4 pb-5 last:pb-0">
                {!last && <span aria-hidden="true" className={cx("absolute left-[15px] top-9 bottom-0 w-px", ui === "passed" ? "bg-passed/50" : "bg-line")} />}
                <span className={cx("relative z-[1] grid size-8 shrink-0 place-items-center rounded-full bg-surface shadow-[inset_0_0_0_1.5px_currentColor]", STATUS[ui].text)} role="img" aria-label={`Stage ${i + 1}: ${STATUS[ui].label}`}>
                  {ui === "passed" ? <Check size={16} strokeWidth={3} aria-hidden /> : <StatusIcon status={ui} size={16} />}
                </span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {role && who ? (
                      <button type="button" onClick={() => onOpenRole(role)} className="agent-text rounded-md font-semibold hover:underline" style={{ "--agent-h": agentToken(role).hue } as React.CSSProperties}>{who}</button>
                    ) : <span className="font-semibold">Stage {i + 1}</span>}
                    {ui !== "passed" && ui !== "idle" && <StatusChip status={ui} size="sm" />}
                    {tries > 1 && <span className="inline-flex items-center gap-1 rounded-full bg-blocked-bg px-2 py-0.5 text-[13px] font-medium text-blocked"><RefreshCw size={12} aria-hidden />{tries} tries</span>}
                  </div>
                  <p className={cx("mt-0.5 break-words", ui === "passed" ? "text-fg-2" : "text-fg")}>{what}</p>
                </div>
              </motion.li>
            );
          })}
        </ol>
      )}

      {onResume && (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl border border-hairline bg-raised p-4">
          <div className="min-w-[200px] flex-1 basis-[220px]">
            <p className="font-semibold">This run stopped</p>
            <p className="text-[13px] text-fg-2">Resume keeps what passed and tries the rest again from this plan. Add guidance in the box below if you want.</p>
          </div>
          <Button variant="primary" onClick={onResume} disabled={busy}><RotateCcw size={16} aria-hidden />{busy ? "Resuming…" : "Resume run"}</Button>
        </div>
      )}

      {view.awaitingApproval && (
        <div className="mt-5 rounded-2xl border border-accent/40 bg-raised p-4">
          <p className="font-semibold">{view.tasks.length > 0 ? "Approve the revised plan to continue" : "Approve this plan to start"}</p>
          <p className="text-[13px] text-fg-2">{view.tasks.length > 0 ? "The Project Manager changed the plan after work started. Nothing continues until you decide." : "Nothing runs until you decide."}</p>
          <label htmlFor="plan-changes" className="mt-3 block text-[13px] font-semibold">Want something different?</label>
          <textarea id="plan-changes" rows={2} value={changes} onChange={(e) => setChanges(e.target.value)} placeholder="For example: also add tests, or leave out the database."
            className="mt-1 w-full resize-y rounded-xl border border-control bg-page px-3 py-2 text-fg placeholder:text-fg-3" />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => onApprove(true)}>Approve and start</Button>
            <Button disabled={!changes.trim()} onClick={() => { onApprove(false, changes.trim()); setChanges(""); }}>Request changes</Button>
            <Button onClick={() => onApprove(false)}>Reject</Button>
          </div>
          <p className="mt-2 text-[13px] text-fg-3">{changes.trim() ? "Request changes sends your note to the Project Manager. It revises the plan and asks you again." : "Write what should change to enable Request changes. Reject stops the run."}</p>
        </div>
      )}
    </section>
  );
}
