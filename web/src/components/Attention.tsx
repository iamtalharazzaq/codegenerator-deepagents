import { guardrailText, type Attention as Attn, type RunView } from "../model";
import { roleLabel } from "../roles";
import { Clamp, Button } from "../ui/bits";
import { StatusIcon, STATUS } from "../ui/Status";

interface Props {
  compact?: boolean;
  view: RunView;
  attn: NonNullable<Attn>;
  onApprove: (approved: boolean) => void;
  onGuidance: () => void;
  onRetry: (text: string) => void;
  onLogs: (taskId?: string) => void;
  onOpenAgent: (role: string) => void;
  onReport: () => void;
}

/** The single most important thing: what is wrong or what is waiting, and the next step to take. */
export function AttentionCard({ compact = false, view, attn, onApprove, onGuidance, onRetry, onLogs, onOpenAgent, onReport }: Props) {
  if (attn.kind === "approval") {
    return (
      <section aria-labelledby="attn-title" className="rounded-xl border border-accent/60 bg-surface p-4">
        <p className="text-[13px] font-semibold uppercase tracking-wide text-accent">Waiting for you</p>
        <h2 id="attn-title" className="mt-1 text-base font-semibold">{attn.title}</h2>
        <p className="mt-1 text-fg-2">Nothing starts until you decide. This is the Project Manager's to-do list:</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-fg">
          {attn.detail.slice(0, 7).map((d) => <li key={d}>{d}</li>)}
        </ol>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => onApprove(true)}>Approve and start</Button>
          <Button onClick={() => onApprove(false)}>Reject</Button>
        </div>
      </section>
    );
  }
  if (attn.kind === "done") {
    return (
      <section aria-labelledby="attn-title" className={`rounded-xl border ${STATUS.passed.ring} bg-surface p-4`}>
        <div className="flex items-center gap-2 text-passed"><StatusIcon status="passed" size={20} /><h2 id="attn-title" className="text-base font-semibold">{attn.title}</h2></div>
        <Clamp lines={3} className="mt-2 text-fg-2"><p>{attn.detail}</p></Clamp>
        <div className="mt-3 flex flex-wrap gap-2">
          {view.zip && <a className="inline-flex items-center rounded-lg bg-accent-bg px-3 py-2 text-sm font-semibold text-on-accent hover:brightness-110" href={`/api/runs/${view.runId}/delivery.zip`} download>Download zip ({view.zip.files} files)</a>}
          <Button onClick={onReport}>View report</Button>
        </div>
      </section>
    );
  }
  const tone = STATUS[attn.ui] ?? STATUS.escalated;
  const retryText = attn.role ? `Retry the ${roleLabel(attn.role)} task${attn.objective ? `: ${attn.objective}` : ""}. Keep what already passed.` : "";
  return (
    <section aria-labelledby="attn-title" className={`rounded-xl border ${tone.ring} bg-surface p-4`}>
      <p className={`flex items-center gap-1.5 text-[13px] font-semibold uppercase tracking-wide ${tone.text}`}><StatusIcon status={attn.ui} size={16} />Attention needed</p>
      <h2 id="attn-title" className="mt-1 text-base font-semibold">{attn.title}</h2>
      <Clamp lines={compact ? 2 : 3} className="mt-1 text-fg-2"><p className="font-mono text-[13px] leading-relaxed break-words">{attn.detail}</p></Clamp>
      {!compact && (attn.tries > 0 || attn.guardrails > 0) && (
        <p className="mt-2 flex flex-wrap gap-2 text-[13px] text-fg-2">
          {attn.tries > 0 && <span className="rounded-md bg-raised px-2 py-0.5">Tries used: {attn.tries}</span>}
          {attn.guardrails > 0 && <span className="rounded-md bg-raised px-2 py-0.5">{attn.guardrails} guardrail hit{attn.guardrails > 1 ? "s" : ""}</span>}
          {view.finished?.summary && <span className="rounded-md bg-raised px-2 py-0.5">{view.finished.seconds ? `Ran ${Math.round(view.finished.seconds / 60)} min` : "Run ended"}</span>}
        </p>
      )}
      {!compact && view.finished?.summary && <Clamp lines={2} className="mt-2 text-fg-2"><p>{view.finished.summary}</p></Clamp>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" onClick={onGuidance}>Resume with guidance</Button>
        {attn.role && <Button onClick={() => onRetry(retryText)}>Retry task</Button>}
        <Button variant="ghost" onClick={() => onLogs(attn.taskId)}>View logs</Button>
        {attn.role && <Button variant="ghost" onClick={() => onOpenAgent(attn.role!)}>Agent details</Button>}
      </div>
      {view.guardrails.length > 0 && <p className="mt-3 text-[13px] text-blocked">{guardrailText(view.guardrails[view.guardrails.length - 1])}</p>}
    </section>
  );
}
