import { useState } from "react";

import { api } from "../api";
import type { RunView } from "../model";
import { Clamp } from "../ui/bits";
import { Markdown } from "./Markdown";

/** What you get at the end: the summary, the zip, and the full report on demand. The status is in the header. */
export function ResultCard({ view }: { view: RunView }) {
  const [report, setReport] = useState<string | null>(null);
  const done = view.status !== "running" && view.status !== "idle";
  if (!done || !view.runId) return null;
  const id = view.runId;
  const load = (open: boolean) => { if (open && report === null) api.report(id).then((r) => setReport(r.report ?? "")).catch(() => setReport("The report is not available.")); };
  const summary = view.finished?.summary || view.finished?.message;
  return (
    <section aria-labelledby="result-title" className="rounded-xl border border-line bg-surface p-4">
      <h2 id="result-title" className="font-semibold">Result</h2>
      {summary && <Clamp lines={4} className="mt-1 text-fg-2"><p className="whitespace-pre-wrap break-words">{summary}</p></Clamp>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {view.status === "passed" && view.zip && <a className="inline-flex items-center rounded-lg bg-accent-bg px-3 py-2 text-sm font-semibold text-on-accent hover:brightness-110" href={`/api/runs/${id}/delivery.zip`} download>Download zip ({view.zip.files} files)</a>}
        {view.status === "passed" && view.secretBlock && <p className="rounded-lg bg-blocked-bg px-3 py-2 text-blocked">The zip was not built: {view.secretBlock.reason}. See the report.</p>}
        {view.status !== "passed" && view.tasks.length > 0 && <a className="inline-flex items-center rounded-lg border border-control bg-raised px-3 py-2 text-sm hover:bg-line/50" href={`/api/runs/${id}/delivery.zip?partial=1`} download>Download partial zip</a>}
      </div>
      <details className="mt-3 border-t border-line pt-2" onToggle={(e) => load((e.target as HTMLDetailsElement).open)}>
        <summary className="text-[13px] font-medium text-accent">Full report</summary>
        <div className="mt-2">{report === null ? <p className="text-fg-2">Loading…</p> : report ? <Markdown text={report} /> : <p className="text-fg-2">No report was written.</p>}</div>
      </details>
    </section>
  );
}
