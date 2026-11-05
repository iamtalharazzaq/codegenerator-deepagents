import { useEffect, useState } from "react";

import { api } from "../api";
import { isResumable, type RunView } from "../model";
import { Markdown } from "./Markdown";

/** The end of a run: the report, and the zip. */
export function ReportTab({ view }: { view: RunView }) {
  const [report, setReport] = useState<string | null>(null);
  const done = view.status !== "running" && view.status !== "idle";
  useEffect(() => {
    if (!view.runId || !done) return;
    api.report(view.runId).then((r) => setReport(r.report)).catch(() => setReport(null));
  }, [view.runId, done, view.status]);
  if (!done) return <p className="p-4 text-fg-2">The report and the zip appear here when the run ends.</p>;
  const id = view.runId;
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        {view.status === "passed" && view.zip && (
          <a className="inline-flex items-center rounded-lg bg-accent-bg px-3 py-2 text-sm font-semibold text-on-accent hover:brightness-110" href={`/api/runs/${id}/delivery.zip`} download>Download zip ({view.zip.files} files)</a>
        )}
        {view.status === "passed" && view.secretBlock && (
          <p className="rounded-lg bg-blocked-bg px-3 py-2 text-blocked">The zip was not built: {view.secretBlock.reason}. Remove the secrets listed in the report, then run again.</p>
        )}
        {view.status !== "passed" && view.tasks.length > 0 && (
          <a className="inline-flex items-center rounded-lg border border-control bg-raised px-3 py-2 text-sm hover:bg-line/50" href={`/api/runs/${id}/delivery.zip?partial=1`} download>Download partial zip</a>
        )}
        {isResumable(view.status) && <span className="text-[13px] text-fg-2">To continue, write guidance in the box under the conversation and resume.</span>}
      </div>
      {report ? <Markdown text={report} /> : <p className="text-fg-2">Loading the report…</p>}
    </div>
  );
}
