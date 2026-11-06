import { ArrowUp, CircleCheck, Info, Lock, MessageSquarePlus, Plus, RotateCcw, Square, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import type { AppConfig, ProjectRow } from "../api";
import { isResumable, type RunView } from "../model";
import { Button, cx } from "../ui/bits";
import { Select, Toggle } from "../ui/Controls";

interface Props {
  view: RunView;
  config: AppConfig | null;
  projects: ProjectRow[];
  selected: string | null;
  value: string;
  onChange: (v: string) => void;
  busy: boolean;
  /** the project a follow-up run should build on, when the person came from a finished run */
  projectHint: string | null;
  retryText: string;
  /** Start opens the conversation with the Project Manager, which answers with a plan in key points */
  onStart: (text: string, concurrency: number, project: string | null, finalReview: boolean) => void;
  onResume: (text: string) => void;
  onCancel: () => void;
  onNew: () => void;
  onFollowUp: () => void;
  onRetry: (text: string) => void;
}

const field = "w-full resize-none rounded-2xl border border-control bg-page px-4 py-3 text-[15px] text-fg placeholder:text-fg-3";

/** Docked at the bottom of the Activity pane. It has four honest states: start a run, give guidance for the next attempt,
 * locked while the run works (and why), and a clean "Run complete" banner when it is finished. */
export function Composer({ view, config, projects, selected, value, onChange, busy, projectHint, retryText, onStart, onResume, onCancel, onNew, onFollowUp, onRetry }: Props) {
  const [finalReview, setFinalReview] = useState(true);
  const [concurrency, setConcurrency] = useState(1);
  const [project, setProject] = useState("");
  useEffect(() => { if (projectHint !== null) setProject(projectHint); }, [projectHint]);

  const resumable = !!selected && isResumable(view.status);
  const running = !!selected && view.status === "running";
  const complete = !!selected && view.status === "passed";
  const waiting = running && (!!view.review || view.awaitingApproval);

  const submit = () => {
    if (busy) return;
    if (resumable) onResume(value.trim());
    else if (!selected && value.trim()) onStart(value.trim(), concurrency, project || config?.default_project || null, finalReview);
  };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } };

  if (complete) {
    return (
      <div className="border-t border-hairline p-4">
        <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-passed/30 bg-passed-bg/40 p-4">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-passed-bg text-passed"><CircleCheck size={22} aria-hidden /></span>
          <div className="min-w-[200px] flex-1 basis-[220px]">
            <p className="font-semibold">Run complete</p>
            <p className="text-[13px] text-fg-2">Everything passed and the result is on the Overview tab. This run can no longer be changed.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={onFollowUp}><MessageSquarePlus size={16} aria-hidden />Start a follow-up run</Button>
            <Button onClick={onNew}><Plus size={16} aria-hidden />New run</Button>
          </div>
        </div>
      </div>
    );
  }

  if (running) {
    return (
      <div className="border-t border-hairline p-4">
        <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-hairline bg-raised p-4">
          <span className={cx("grid size-10 shrink-0 place-items-center rounded-xl", waiting ? "bg-blocked-bg text-blocked" : "bg-running-bg text-running")}><Lock size={18} aria-hidden /></span>
          <div className="min-w-[200px] flex-1 basis-[220px]">
            <p className="font-semibold">{waiting ? "Waiting for your decision" : "Run in progress"}</p>
            <p className="text-[13px] text-fg-2">{waiting ? (view.review ? "Review the result on the Overview tab to deliver the zip or ask for changes." : "Approve the plan, ask for changes or reject it on the Overview tab.") : "The input is locked while the agents work. You can stop the run, or wait for it to finish."}</p>
          </div>
          <Button variant="danger" onClick={onCancel}><Square size={14} aria-hidden fill="currentColor" />Stop run</Button>
        </div>
      </div>
    );
  }

  return (
    <form className="border-t border-hairline p-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="guidance" className="text-[13px] font-semibold">{resumable ? "Guidance for the next attempt" : "What should be built?"}</label>
      {resumable && (
        <p id="guidance-help" className="mb-2 mt-1 flex items-start gap-2 rounded-xl bg-raised px-3 py-2 text-[13px] text-fg-2">
          <Info size={14} aria-hidden className="mt-0.5 shrink-0 text-accent" />
          On submit the run resumes: the Project Manager is told what passed and what failed, keeps the passed work, and tries the failed work again with your note. This uses the model.
        </p>
      )}
      <textarea
        id="guidance" rows={resumable ? 3 : 2} value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={onKey} aria-describedby={resumable ? "guidance-help" : "compose-help"}
        placeholder={resumable ? "For example: the backend files already exist in backend/, finish and verify them." : "For example: add a password reset flow."}
        className={cx(field, "mt-1")}
      />
      {!resumable && (
        <>
          <div className="mt-3">
            <Toggle checked={finalReview} onChange={setFinalReview} title="Review before the zip" hint="You can ask for changes before the zip is built." />
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_9rem]">
            <Select label="Project" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">New project (empty)</option>
              {projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </Select>
            <Select label="Agents at once" value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>
          </div>
          <p id="compose-help" className="mt-2 text-[13px] text-fg-3">{project ? "Builds on that project's files; the zip will hold the whole project." : "A new project starts empty, so the zip holds only what this request builds. Start opens a conversation: the Project Manager replies with a plan in key points before anything is built."}</p>
        </>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] text-fg-3">Ctrl+Enter to send</span>
        <div className="flex flex-wrap gap-2">
          {resumable && retryText && <Button onClick={() => onRetry(retryText)}><Wrench size={16} aria-hidden />Retry task</Button>}
          <Button variant="primary" type="submit" disabled={busy || (!resumable && !value.trim())}>
            {resumable ? <RotateCcw size={16} aria-hidden /> : <ArrowUp size={16} aria-hidden />}{busy ? "Working…" : resumable ? "Resume run" : "Start"}
          </Button>
        </div>
      </div>
      {resumable && retryText && <p className="mt-2 text-[13px] text-fg-3">Retry task fills in a note for you to read and edit before you resume.</p>}
    </form>
  );
}
