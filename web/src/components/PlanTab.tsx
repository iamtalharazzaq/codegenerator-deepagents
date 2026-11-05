import { guardrailText, roleOfTodo, todoUi, triesForTodo, type RunView } from "../model";
import { roleLabel } from "../roles";
import { StatusChip } from "../ui/Status";

/** The current plan as a checklist with status and tries, the reason for the latest change in one line, and the full
 * revision history folded away until asked for. */
export function PlanTab({ view, onOpenAgent }: { view: RunView; onOpenAgent: (role: string) => void }) {
  if (!view.todos.length) return <p className="p-4 text-fg-2">The Project Manager's to-do list appears here.</p>;
  const latest = view.todoChanges[view.todoChanges.length - 1];
  const hits = view.tasks.flatMap((t) => t.guardrails.map((g) => ({ ...g, role: t.role })));
  return (
    <div className="space-y-4 p-4">
      {latest?.why && (
        <p className="rounded-lg bg-raised px-3 py-2 text-fg"><span className="font-semibold">Why the plan changed: </span>{latest.why}</p>
      )}
      <ol className="space-y-1.5" aria-label="Current plan">
        {view.todos.map((t) => {
          const ui = todoUi(view, t);
          const role = roleOfTodo(t.content);
          const tries = triesForTodo(view, t);
          return (
            <li key={t.content} className="flex items-start gap-3 rounded-lg border border-line px-3 py-2">
              <span className="mt-0.5"><StatusChip status={ui} size="sm" /></span>
              <span className="min-w-0 flex-1">
                {role ? <button type="button" onClick={() => onOpenAgent(role)} className="text-left hover:underline">{t.content}</button> : t.content}
                {tries > 0 && <span className="ml-2 text-[13px] text-fg-3">{tries} {tries === 1 ? "try" : "tries"}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <details className="rounded-lg border border-line">
        <summary className="px-3 py-2 font-medium">Revision history ({view.todoChanges.length})</summary>
        <div className="space-y-3 border-t border-line p-3">
          {view.todoChanges.length === 0 && <p className="text-fg-2">The plan has not changed since it was written.</p>}
          {view.todoChanges.map((c, i) => (
            <div key={c.seq}>
              <p className="font-medium">Revision {i + 1}{c.why ? <span className="font-normal text-fg-2">: {c.why}</span> : null}</p>
              <ul className="mt-1 space-y-1 font-mono text-[13px]">
                {c.added.map((a) => <li key={`a${a}`} className="rounded bg-passed-bg px-2 py-1 text-passed"><span aria-label="Added">+ </span>{a}</li>)}
                {c.removed.map((r) => <li key={`r${r}`} className="rounded bg-escalated-bg px-2 py-1 text-escalated"><span aria-label="Removed">− </span>{r}</li>)}
                {c.completed.map((d) => <li key={`c${d}`} className="rounded bg-raised px-2 py-1 text-fg-2"><span aria-label="Completed">✓ </span>{d}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </details>
      {hits.length > 0 && (
        <details className="rounded-lg border border-line">
          <summary className="px-3 py-2 font-medium">Guardrail hits ({hits.length})</summary>
          <ul className="space-y-1 border-t border-line p-3">
            {hits.map((g) => <li key={g.seq} className="text-[13px] text-fg-2"><span className="font-semibold text-fg">{roleLabel(g.role)}:</span> {guardrailText(g)}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
