import { motion } from "framer-motion";
import { Eye, Flag, RotateCcw, ScrollText, TriangleAlert, Wrench } from "lucide-react";

import { allGuardrails, guardrailText, type Blocker, type RunView } from "../model";
import { MOTION, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Button, cx } from "../ui/bits";

interface Props {
  view: RunView;
  blocker: Blocker;
  onGuidance: () => void;
  onRetry: (text: string) => void;
  onShow: () => void;
  onLogs: () => void;
  /** a short version for the phone's Activity tab, where the composer is right below */
  compact?: boolean;
}

/** Only when the run is stuck. It sits at the top of the right pane and says who failed, why in one line, every guardrail
 * warning (merged in, no separate banners) and the three things you can do next. */
export function AttentionCard({ view, blocker, onGuidance, onRetry, onShow, onLogs, compact = false }: Props) {
  const tone = STATUS[blocker.ui];
  const task = view.tasks.find((t) => t.id === blocker.taskId);
  const cause = (task?.reason || view.finished?.message || "").replace(/\s+/g, " ").trim();
  const hits = allGuardrails(view);
  const retry = blocker.objective ? `Retry: ${blocker.objective}. Keep what already passed.` : "";
  return (
    <motion.section
      aria-labelledby="attention-title" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={MOTION.base}
      className={cx("raised relative overflow-hidden", compact ? "p-4" : "p-5", tone.ring, "bg-[linear-gradient(135deg,color-mix(in_srgb,var(--escalated-bg)_80%,var(--raised)),var(--raised)_70%)]")}
    >
      <span aria-hidden="true" className={cx("glow-pulse absolute inset-y-0 left-0 w-1", tone.dot)} />
      <div className="flex items-start gap-4">
        {blocker.role ? <AgentAvatar role={blocker.role} size={compact ? "md" : "lg"} /> : <span className={cx("grid size-12 place-items-center rounded-2xl", tone.chip)}><TriangleAlert size={24} aria-hidden /></span>}
        <div className="min-w-0 flex-1">
          <p className={cx("flex items-center gap-1.5 text-[13px] font-semibold uppercase tracking-wide", tone.text)}><TriangleAlert size={14} aria-hidden />Attention needed</p>
          <h2 id="attention-title" className="mt-0.5 text-[17px] font-semibold tracking-tight">{blocker.title}</h2>
          {cause && <p className="mt-1 truncate text-fg-2" title={cause}>{cause}</p>}
        </div>
      </div>

      {compact && hits.length > 0 && <p className="mt-2 flex items-center gap-1.5 text-[13px] text-blocked"><Flag size={14} aria-hidden />{hits.length} guardrail {hits.length === 1 ? "warning" : "warnings"}: see Overview</p>}
      {!compact && hits.length > 0 && (
        <ul className="mt-4 space-y-1.5" aria-label="Guardrail warnings">
          {hits.slice(0, 4).map((g) => (
            <li key={g.seq} className="flex items-start gap-2 rounded-xl bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
              <Flag size={14} aria-hidden className="mt-0.5 shrink-0" /><span className="min-w-0 break-words">{guardrailText(g)}</span>
            </li>
          ))}
          {hits.length > 4 && <li className="px-1 text-[13px] text-fg-3">and {hits.length - 4} more in the event log</li>}
        </ul>
      )}

      <div className={cx("flex flex-wrap gap-2", compact ? "mt-3" : "mt-4")}>
        <Button variant="primary" onClick={onGuidance}><RotateCcw size={16} aria-hidden />Resume with guidance</Button>
        {retry && !compact && <Button onClick={() => onRetry(retry)}><Wrench size={16} aria-hidden />Retry task</Button>}
        <Button variant="ghost" onClick={onLogs}><ScrollText size={16} aria-hidden />View logs</Button>
        {blocker.taskId && !compact && <Button variant="ghost" onClick={onShow}><Eye size={16} aria-hidden />Show the step</Button>}
      </div>
    </motion.section>
  );
}
