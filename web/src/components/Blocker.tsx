import type { Blocker as B } from "../model";
import { Button } from "../ui/bits";
import { StatusIcon, STATUS } from "../ui/Status";

/** Only when the run is stuck: what stopped it and the next step. The reason itself is on the task card. */
export function BlockerCard({ blocker, onGuidance, onRetry, onShow, onLogs }: { blocker: B; onGuidance: () => void; onRetry: (text: string) => void; onShow: () => void; onLogs: () => void }) {
  const tone = STATUS[blocker.ui];
  const retry = blocker.objective ? `Retry: ${blocker.objective}. Keep what already passed.` : "";
  return (
    <section aria-labelledby="blocker-title" className={`rounded-xl border ${tone.ring} bg-surface p-4`}>
      <h2 id="blocker-title" className={`flex items-center gap-2 font-semibold ${tone.text}`}><StatusIcon status={blocker.ui} size={18} />{blocker.title}</h2>
      <p className="mt-1 text-fg-2">The run is waiting for you.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" onClick={onGuidance}>Resume with guidance</Button>
        {retry && <Button onClick={() => onRetry(retry)}>Retry this task</Button>}
        {blocker.taskId && <Button variant="ghost" onClick={onShow}>Show the task</Button>}
        <Button variant="ghost" onClick={onLogs}>Open log</Button>
      </div>
    </section>
  );
}
