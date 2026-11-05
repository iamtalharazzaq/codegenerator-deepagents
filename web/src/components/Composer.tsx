import { useState } from "react";

import type { AppConfig, ProjectRow } from "../api";
import { isResumable, type RunView } from "../model";
import { Button } from "../ui/bits";

interface Props {
  view: RunView;
  config: AppConfig | null;
  projects: ProjectRow[];
  selected: string | null;
  value: string;
  onChange: (v: string) => void;
  busy: boolean;
  onStart: (text: string, approvePlan: boolean, concurrency: number, project: string | null, finalReview: boolean) => void;
  onResume: (text: string) => void;
  onCancel: () => void;
  onNew: () => void;
}

/** One box with three honest modes: start a run, give guidance for the next attempt, or locked with the reason why. */
export function Composer({ view, projects, config, selected, value, onChange, busy, onStart, onResume, onCancel, onNew }: Props) {
  const [approvePlan, setApprovePlan] = useState(true);
  const [finalReview, setFinalReview] = useState(true);
  const [concurrency, setConcurrency] = useState(1);
  const [project, setProject] = useState("");
  const resumable = !!selected && isResumable(view.status);
  const running = view.status === "running";
  const finishedOk = !!selected && view.status === "passed";
  const locked = running || finishedOk;
  const submit = () => {
    if (busy || locked) return;
    if (resumable) onResume(value.trim());
    else if (value.trim()) onStart(value.trim(), approvePlan, concurrency, project || config?.default_project || null, finalReview);
  };
  const label = resumable ? "Guidance for the next attempt" : running ? "Run in progress" : finishedOk ? "Run finished" : "What should be built?";
  const help = resumable
    ? "Sending resumes this run. The Project Manager is told what passed and what failed, keeps the passed work, and tries the failed work again with your note. This uses the model."
    : view.review
      ? "The work is finished and waiting for your review. Use the card on the right to deliver it or ask for changes."
    : running
      ? "The run is working. You can cancel it, or wait for it to finish."
      : finishedOk
        ? "This run is finished. Start a new run to build something else."
        : "Describe the change. The Project Manager plans it and delegates to the specialists.";
  return (
    <form className="border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="guidance" className="text-[13px] font-semibold text-fg">{label}</label>
      <p id="guidance-help" className="mb-2 mt-0.5 text-[13px] text-fg-2">{help}</p>
      <textarea
        id="guidance" rows={3} value={value} disabled={locked} aria-describedby="guidance-help" onChange={(e) => onChange(e.target.value)}
        placeholder={resumable ? "For example: the backend files already exist in backend/, finish and verify them." : "For example: add a password reset flow."}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}
        className="w-full resize-y rounded-lg border border-control bg-page px-3 py-2 text-fg placeholder:text-fg-3 disabled:opacity-60"
      />
      {!resumable && !locked && (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1.5 text-[13px] text-fg-2">
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={approvePlan} onChange={(e) => setApprovePlan(e.target.checked)} />Ask me to approve the plan</label>
          <label className="inline-flex items-center gap-2"><input type="checkbox" checked={finalReview} onChange={(e) => setFinalReview(e.target.checked)} />Ask me to review before the zip</label>
          <label className="inline-flex items-center gap-2">Project
            <select value={project} onChange={(e) => setProject(e.target.value)} aria-describedby="project-help" className="max-w-[210px] rounded-md border border-control bg-page px-1.5 py-0.5 text-fg">
              <option value="">New project (empty)</option>
              {projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </label>
          <label className="inline-flex items-center gap-2">Run at once
            <select value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} className="rounded-md border border-control bg-page px-1.5 py-0.5 text-fg">{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
        </div>
      )}
      {!resumable && !locked && <p id="project-help" className="mt-1.5 text-[13px] text-fg-3">{project ? "Builds on that project's files; the zip will hold the whole project." : "A new project starts empty, so the zip holds only what this request builds."}</p>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] text-fg-3">{locked ? "" : "Ctrl+Enter to send"}</span>
        {running ? <Button onClick={onCancel}>Cancel run</Button>
          : finishedOk ? <Button variant="primary" onClick={onNew}>New run</Button>
          : <Button variant="primary" type="submit" disabled={busy || (!resumable && !value.trim())}>{resumable ? "Resume with guidance" : "Start run"}</Button>}
      </div>
    </form>
  );
}
