import { Download, FileArchive, ScrollText, TriangleAlert } from "lucide-react";

import { formatDuration, type RunView } from "../model";
import { Celebrate } from "../ui/Celebrate";
import { buttonClass, Button, cx, Skeleton } from "../ui/bits";
import { Markdown } from "../ui/Markdown";

/** The hero of the Overview. Passed: calm, green, the deliverable first. Stopped: the partial result. Running: a skeleton. */
export function ResultCard({ view, celebrate, onReport }: { view: RunView; celebrate: boolean; onReport: () => void }) {
  const id = view.runId;
  const finished = view.finished;
  if (!id || view.status === "idle") return null;

  if (view.status === "running") {
    return (
      <section aria-labelledby="result-title" aria-busy="true" className="surface p-5">
        <h2 id="result-title" className="font-semibold">Result</h2>
        <p className="mt-1 text-fg-2">The summary and the download appear here when the run finishes.</p>
        <div className="mt-4 space-y-2" aria-hidden="true"><Skeleton className="h-4 w-4/5" /><Skeleton className="h-4 w-3/5" /><Skeleton className="h-10 w-40" /></div>
      </section>
    );
  }

  const passed = view.status === "passed";
  const summary = finished?.summary || finished?.message || "";
  const files = view.zip?.files;
  return (
    <section
      aria-labelledby="result-title"
      className={cx("raised relative overflow-hidden p-6", passed ? "border-passed/30 bg-[radial-gradient(520px_220px_at_0%_0%,color-mix(in_srgb,var(--passed)_14%,transparent),transparent_70%),var(--raised)]" : "")}
    >
      <header className="flex items-center gap-4">
        {passed
          ? <Celebrate burst={celebrate} />
          : <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-blocked-bg text-blocked"><TriangleAlert size={24} aria-hidden /></span>}
        <div className="min-w-0">
          <h2 id="result-title" className="text-xl font-semibold tracking-tight">{passed ? "Delivered" : "Partial result"}</h2>
          <p className="text-fg-2">
            {passed ? `${view.tasks.filter((t) => t.status === "pass").length} tasks passed` : "The run stopped before it finished"}
            {finished ? ` · ${formatDuration(finished.seconds)}` : ""}
          </p>
        </div>
      </header>

      {summary && <div className="mt-5"><Markdown text={summary} /></div>}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        {passed && view.zip && (
          <a href={`/api/runs/${id}/delivery.zip`} download className={buttonClass("primary", "lg")}><Download size={18} aria-hidden />Download zip</a>
        )}
        {!passed && view.tasks.length > 0 && (
          <a href={`/api/runs/${id}/delivery.zip?partial=1`} download className={buttonClass("secondary", "lg")}><Download size={18} aria-hidden />Download partial zip</a>
        )}
        {passed && files !== undefined && (
          <span className="inline-flex h-9 items-center gap-1.5 rounded-full bg-raised px-3 text-[13px] text-fg-2 shadow-[inset_0_0_0_1px_var(--hairline)]"><FileArchive size={14} aria-hidden />{files} files</span>
        )}
        <Button variant="ghost" size="lg" onClick={onReport}><ScrollText size={18} aria-hidden />Full report</Button>
      </div>
      {passed && view.secretBlock && (
        <p className="mt-4 rounded-xl bg-blocked-bg px-4 py-3 text-blocked">The zip was not built: {view.secretBlock.reason}. See the report.</p>
      )}
    </section>
  );
}

/** Four numbers about the run, each printed with its label. */
export function StatsRow({ stats }: { stats: Array<{ label: string; value: string; hint?: string }> }) {
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Run statistics">
      {stats.map((s) => (
        <div key={s.label} className="surface px-4 py-3">
          <dt className="text-[13px] text-fg-3">{s.label}</dt>
          <dd className="mt-0.5"><span className="block text-xl font-semibold tabular-nums tracking-tight">{s.value}</span>{s.hint && <span className="block text-[13px] text-fg-3">{s.hint}</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
