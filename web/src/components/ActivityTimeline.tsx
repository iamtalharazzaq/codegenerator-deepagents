import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { isWorking, nowLine, taskUi, timeline, type RunView } from "../model";
import { MOTION, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Collapse, cx, Skeleton } from "../ui/bits";
import { StatusIcon } from "../ui/StatusChip";
import { AgentStepCard } from "./AgentStepCard";

const EXAMPLES = ["Make a calculator", "Create a REST API for a todo list", "Add a password reset flow"];

/** The Project Manager's reasoning is long, so the timeline shows one line and keeps the rest behind "Show reasoning". */
function PmEntry({ text, replan }: { text: string; replan: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex items-start gap-3">
      <span className="rounded-xl bg-surface"><AgentAvatar role="project_manager" /></span>
      <div className="min-w-0 flex-1 pt-1">
        <p className="font-semibold tracking-tight">Project Manager <span className="font-normal text-fg-3">{replan ? "replanned" : "planned the work"}</span></p>
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-0.5 flex w-full items-start gap-1 text-left text-[13px] text-fg-2 hover:text-fg">
          <span className={cx("min-w-0 flex-1", !open && "truncate")}>{open ? "" : text}</span>
          <span className="inline-flex shrink-0 items-center gap-1 font-medium text-accent">{open ? "Hide reasoning" : "Show reasoning"}<ChevronDown size={14} aria-hidden className={cx("transition-transform duration-200", open && "rotate-180")} /></span>
        </button>
        <Collapse open={open}><p className="whitespace-pre-wrap break-words pt-1 text-fg-2">{text}</p></Collapse>
      </div>
    </div>
  );
}

/** The one line that says what is happening right now. Screen readers hear it as a polite status. */
function NowStrip({ view }: { view: RunView }) {
  const now = nowLine(view);
  return (
    <div role="status" aria-live="polite" className="min-h-0">
      <AnimatePresence initial={false}>
        {now && (
          <motion.p key={now.ui} initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={MOTION.base}
            className={cx("flex items-center gap-2 overflow-hidden border-b border-hairline px-5 py-2 text-[13px] font-medium", STATUS[now.ui].text)}>
            <StatusIcon status={now.ui} size={14} /><span className="min-w-0 flex-1 truncate">{now.text}</span>
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

interface Props {
  view: RunView;
  focus: { id: string; n: number } | null;
  onLogs: (taskId?: string) => void;
  onOpenAgent: (role: string) => void;
  onExample: (text: string) => void;
}

/** The run as a vertical timeline: the prompt, the Project Manager's plan, then one card per delegation. Scrolls on its own. */
export function ActivityTimeline({ view, focus, onLogs, onOpenAgent, onExample }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const items = timeline(view);
  const planning = view.status === "running" && view.tasks.length === 0 && view.todos.length === 0;

  useEffect(() => {
    const toEnd = () => box.current?.scrollTo({ top: box.current.scrollHeight });
    const frame = requestAnimationFrame(toEnd);
    return () => cancelAnimationFrame(frame);
  }, [items.length, view.tasks.length, view.runId]);
  useEffect(() => {
    if (focus) document.getElementById(`task-${focus.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  if (!items.length) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-y-auto p-8 text-center">
        <span className="agent-tint grid size-14 place-items-center rounded-2xl" style={{ "--agent-h": 252 } as React.CSSProperties}><Sparkles size={26} aria-hidden /></span>
        <div>
          <h2 className="text-[17px] font-semibold tracking-tight">What should be built?</h2>
          <p className="mx-auto mt-1 max-w-[44ch] text-fg-2">Describe the change. The Project Manager makes a plan, hands each piece to the right specialist, reads every result, and decides what comes next.</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2" role="group" aria-label="Examples">
          {EXAMPLES.map((e) => <button key={e} type="button" onClick={() => onExample(e)} className="h-9 rounded-full border border-hairline bg-raised px-4 text-[13px] text-fg-2 transition-colors hover:text-fg">{e}</button>)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <NowStrip view={view} />
      <div ref={box} className="min-h-0 flex-1 overflow-y-auto px-5 py-5" tabIndex={0} role="region" aria-label="Activity timeline" aria-busy={isWorking(view)}>
        <ol className="relative space-y-5">
          <span aria-hidden="true" className="absolute bottom-4 left-[18px] top-4 w-px bg-line" />
          {items.map((it) => {
            if (it.kind === "user") {
              return (
                <li key={`u${it.seq}`} className="relative pl-0">
                  <p className="ml-auto max-w-[92%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md border border-hairline bg-gradient-to-br from-[var(--accent-from)]/25 to-[var(--accent-to)]/20 px-4 py-3 text-[15px] shadow-[inset_0_1px_0_var(--highlight)]">{it.text}</p>
                </li>
              );
            }
            if (it.kind === "note") {
              return <li key={`n${it.seq}`} className={cx("relative ml-12 rounded-xl px-3 py-2 text-[13px]", it.tone === "warn" ? "bg-blocked-bg text-blocked" : "bg-raised text-fg-2")}>{it.text}</li>;
            }
            if (it.kind === "pm") return <li key={`pm${it.seq}`} className="relative"><PmEntry text={it.text} replan={it.replan} /></li>;
            return (
              <li key={`w${it.seq}`} className="relative ml-12" aria-label={it.parallel ? `${it.tasks.length} tasks ran at the same time` : undefined}>
                <span aria-hidden="true" className={cx("absolute -left-[35px] top-6 size-[11px] rounded-full ring-4 ring-[var(--surface)]", STATUS[taskUi(view, it.tasks[0])].dot)} />
                {it.parallel && <p className="mb-2 text-[13px] font-medium text-fg-3">{it.tasks.length} at once</p>}
                <div className={it.parallel ? "grid gap-3 xl:grid-cols-2" : ""}>
                  {it.tasks.map((t) => <AgentStepCard key={t.id} view={view} task={t} lit={focus?.id === t.id} onLogs={onLogs} onOpenAgent={onOpenAgent} />)}
                </div>
              </li>
            );
          })}
          {planning && (
            <li className="relative ml-12 space-y-2" aria-hidden="true">
              <Skeleton className="h-4 w-2/5" /><Skeleton className="h-20" />
            </li>
          )}
        </ol>
      </div>
    </div>
  );
}
