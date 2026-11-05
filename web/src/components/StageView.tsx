import { formatDuration, roleOfTodo, taskUi, todoUi, waves, type Attention, type RunView, type TaskView } from "../model";
import { roleLabel } from "../roles";
import { StatusChip, STATUS } from "../ui/Status";

/** Work in the order it happened. Each column is a stage; tasks in one column ran at the same time, and every stage
 * waited for the one before it. Not-yet-started work sits in the last column with what it is waiting on. */
export function StageView({ view, attn, onOpen }: { view: RunView; attn: Attention; onOpen: (role: string, taskId?: string) => void }) {
  const stages = waves(view.tasks);
  const blocker = attn && attn.kind === "blocked" && attn.role ? roleLabel(attn.role) : null;
  const notStarted = view.todos.filter((t) => t.status === "pending");
  if (!stages.length && !notStarted.length) {
    return <p className="p-4 text-fg-2">Stages appear here as the Project Manager delegates work.</p>;
  }
  const card = (t: TaskView) => {
    const ui = taskUi(view, t);
    const seconds = (t.endTs ?? Date.now() / 1000) - t.startTs;
    return (
      <li key={t.id}>
        <button type="button" onClick={() => onOpen(t.role, t.id)} aria-label={`${roleLabel(t.role)}, try ${t.attempt}, ${STATUS[ui].label}. Open details.`}
          className={`w-full rounded-lg border ${STATUS[ui].ring} bg-raised p-3 text-left hover:brightness-125`}>
          <span className="block font-semibold">{roleLabel(t.role)}</span>
          <span className="mt-1 block"><StatusChip status={ui} size="sm" /></span>
          <span className="mt-1 line-clamp-2 block text-[13px] text-fg-2">{t.objective}</span>
          <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-fg-3">
            <span>Try {t.attempt}</span>
            <span className="font-mono">{formatDuration(seconds)}</span>
            {t.guardrails.length > 0 && <span className="text-blocked">{t.guardrails.length} guardrail hit{t.guardrails.length > 1 ? "s" : ""}</span>}
          </span>
        </button>
      </li>
    );
  };
  return (
    <div className="overflow-x-auto p-4" tabIndex={0} aria-label="Stages, scroll sideways for more">
      <ol className="flex min-w-max items-stretch gap-2">
        {stages.map((w, i) => (
          <li key={w.index} className="flex items-stretch gap-2">
            {i > 0 && <span aria-hidden="true" className="flex items-center text-fg-3"><svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10h11M11 5l5 5-5 5" /></svg></span>}
            <div className="w-[205px]">
              <h3 className="text-[13px] font-semibold uppercase tracking-wide text-fg-2">Stage {w.index}{w.parallel ? " · in parallel" : ""}</h3>
              {w.waitsFor.length > 0 && <p className="mb-2 text-[13px] text-fg-3">after {w.waitsFor.map(roleLabel).join(", ")}</p>}
              {w.waitsFor.length === 0 && <p className="mb-2 text-[13px] text-fg-3">first</p>}
              <ul className="space-y-2">{w.tasks.map(card)}</ul>
            </div>
          </li>
        ))}
        {notStarted.length > 0 && (
          <li className="flex items-stretch gap-2">
            {stages.length > 0 && <span aria-hidden="true" className="flex items-center text-fg-3"><svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="3 3" strokeLinecap="round"><path d="M4 10h11" /></svg></span>}
            <div className="w-[205px]">
              <h3 className="text-[13px] font-semibold uppercase tracking-wide text-fg-2">Not started</h3>
              <p className="mb-2 text-[13px] text-fg-3">{blocker ? `blocked by ${blocker}` : "waiting for earlier stages"}</p>
              <ul className="space-y-2">
                {notStarted.map((t) => {
                  const role = roleOfTodo(t.content);
                  const ui = todoUi(view, t);
                  return (
                    <li key={t.content} className={`rounded-lg border border-dashed ${STATUS[ui].ring} p-3`}>
                      <span className="block font-semibold">{role ? roleLabel(role) : "Task"}</span>
                      <span className="mt-1 block"><StatusChip status={ui} size="sm" /></span>
                      <span className="mt-1 line-clamp-2 block text-[13px] text-fg-2">{t.content.replace(/^[^:]+:\s*/, "")}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </li>
        )}
      </ol>
      <p className="mt-3 text-[13px] text-fg-3">Tasks in the same stage ran together. Each stage started after the previous one finished.</p>
    </div>
  );
}
