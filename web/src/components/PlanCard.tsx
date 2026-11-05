import { roleOfTodo, todoUi, triesForTodo, type RunView } from "../model";
import { Button, Clamp } from "../ui/bits";
import { StatusIcon, STATUS } from "../ui/Status";

/** The Project Manager's plan, in one place: it shows the planning while it happens, the checklist with live status,
 * the Project Manager's reasoning, the approval buttons, and every change to the plan folded into "History". */
export function PlanCard({ view, onApprove, onOpenRole }: { view: RunView; onApprove: (approved: boolean) => void; onOpenRole: (role: string) => void }) {
  const planning = view.status === "running" && view.todos.length === 0 && !view.awaitingApproval;
  const latest = view.pmNotes[view.pmNotes.length - 1];
  const older = view.pmNotes.slice(0, -1);
  const hasHistory = view.todoChanges.length > 0 || older.length > 0;
  if (view.status === "idle" && !view.todos.length) return null;
  return (
    <section aria-labelledby="plan-title" className="rounded-xl border border-line bg-surface p-4">
      <h2 id="plan-title" className="flex items-center gap-2 font-semibold">
        Plan
        {planning && <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-running"><StatusIcon status="running" size={14} />Project Manager is planning…</span>}
      </h2>
      {latest && (
        <div className="mt-2">
          <p className="text-[13px] font-semibold text-accent">Project Manager</p>
          <Clamp lines={3} className="text-fg"><p className="whitespace-pre-wrap break-words">{latest.text}</p></Clamp>
        </div>
      )}
      {planning && (
        <div className="mt-3 space-y-2" aria-hidden="true">
          {[78, 62, 70].map((w) => <div key={w} className="h-4 animate-pulse rounded bg-line/70" style={{ width: `${w}%` }} />)}
        </div>
      )}
      {view.todos.length > 0 && (
        <ol className="mt-3 space-y-1" aria-label="Plan items">
          {view.todos.map((t) => {
            const ui = todoUi(view, t);
            const role = roleOfTodo(t.content);
            const tries = triesForTodo(view, t);
            const word = ui === "blocked" || ui === "escalated" || ui === "failed" ? STATUS[ui].label : null;
            return (
              <li key={t.content} className="flex items-start gap-2.5 rounded-md px-1 py-1">
                <span className={`mt-0.5 ${STATUS[ui].text}`} role="img" aria-label={STATUS[ui].label}><StatusIcon status={ui} size={18} /></span>
                <span className={`min-w-0 flex-1 ${ui === "passed" ? "text-fg-2" : "text-fg"}`}>
                  {role ? <button type="button" onClick={() => onOpenRole(role)} className="text-left hover:underline">{t.content}</button> : t.content}
                  {tries > 1 && <span className="ml-2 text-[13px] text-fg-3">{tries} tries</span>}
                  {word && <span className={`ml-2 text-[13px] font-medium ${STATUS[ui].text}`}>{word}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {view.awaitingApproval && (
        <div className="mt-3 rounded-lg border border-accent/60 bg-raised p-3">
          <p className="font-semibold">Approve this plan to start</p>
          <p className="text-[13px] text-fg-2">Nothing runs until you decide.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => onApprove(true)}>Approve and start</Button>
            <Button onClick={() => onApprove(false)}>Reject</Button>
          </div>
        </div>
      )}
      {hasHistory && (
        <details className="mt-3 border-t border-line pt-2">
          <summary className="text-[13px] font-medium text-accent">History ({view.todoChanges.length + older.length})</summary>
          <div className="mt-2 space-y-3">
            {older.map((n) => <Clamp key={n.seq} lines={2} className="text-fg-2"><p><span className="font-semibold text-accent">Project Manager: </span>{n.text}</p></Clamp>)}
            {view.todoChanges.filter((c) => c.added.length || c.removed.length).map((c) => (
              <ul key={c.seq} className="space-y-1 font-mono text-[13px]">
                {c.added.map((a) => <li key={`a${a}`} className="rounded bg-passed-bg px-2 py-1 text-passed"><span aria-label="Added">+ </span>{a}</li>)}
                {c.removed.map((r) => <li key={`r${r}`} className="rounded bg-escalated-bg px-2 py-1 text-escalated"><span aria-label="Removed">− </span>{r}</li>)}
              </ul>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
