import { useEffect, useState } from "react";

import { api } from "../api";
import type { RunView } from "../model";
import { Markdown } from "./Markdown";

/** The end of a run: the report, and the zip. */
export function Report({ view, resumable }: { view: RunView; resumable: boolean }) {
  const [report, setReport] = useState<string | null>(null);
  const done = view.status !== "running" && view.status !== "idle";
  useEffect(() => {
    if (!view.runId || !done) return;
    api.report(view.runId).then((r) => setReport(r.report)).catch(() => setReport(null));
  }, [view.runId, done, view.status]);
  if (!done) return <p className="empty">The report and the zip appear here when the run ends.</p>;
  const id = view.runId;
  return (
    <div className="report">
      <div className="actions">
        {view.status === "passed" && view.zip && (
          <a className="btn primary" href={`/api/runs/${id}/delivery.zip`} download>Download zip ({view.zip.files} files)</a>
        )}
        {view.status === "passed" && view.secretBlock && (
          <p className="guard">The zip was not built: {view.secretBlock.reason}. Remove the secrets listed in the report, then run again.</p>
        )}
        {view.status !== "passed" && view.tasks.length > 0 && (
          <a className="btn" href={`/api/runs/${id}/delivery.zip?partial=1`} download>Download partial zip</a>
        )}
        {resumable && <span className="hint">Send a message in the chat to resume this run with your guidance.</span>}
      </div>
      {report ? <Markdown text={report} /> : <p className="empty">Loading the report…</p>}
    </div>
  );
}
