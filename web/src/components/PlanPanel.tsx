import { useState } from "react";

import { api } from "../api";
import { guardrailText, stages, type RunView, type TaskView } from "../model";
import { roleLabel } from "../roles";

const WORD: Record<string, string> = {
  pending: "waiting", in_progress: "working", pass: "passed", fail: "failed", escalated: "escalated", blocked: "blocked", superseded: "removed",
};
const BADGE: Record<string, string> = {
  pending: "b-pending", in_progress: "b-active", pass: "b-pass", fail: "b-fail", escalated: "b-esc", blocked: "b-esc", superseded: "b-pending",
};

function TaskRow({ task, view, names }: { task: TaskView; view: RunView; names: Map<string, TaskView> }) {
  const [open, setOpen] = useState(false);
  const [artifact, setArtifact] = useState<string | null>(null);
  const waits = task.depends_on.map((d) => names.get(d)).filter((d): d is TaskView => !!d);
  const toggle = () => {
    setOpen(!open);
    if (!open && view.runId && task.attempt > 0 && artifact === null) {
      api.artifact(view.runId, `${task.id}.md`).then(setArtifact).catch(() => setArtifact("(no result file yet)"));
    }
  };
  const tools = view.toolLines[task.id] ?? [];
  return (
    <>
      <button className="row" aria-expanded={open} onClick={toggle}>
        <span className={`badge ${BADGE[task.status]}`}>{WORD[task.status]}</span>
        <span>
          {task.objective}
          {waits.length > 0 && <small className="waits">waits for {waits.map((w) => roleLabel(w.role)).join(", ")}</small>}
        </span>
        <span className="who">{roleLabel(task.role)}{task.attempt ? ` · try ${task.attempt}/2` : ""}</span>
      </button>
      {open && (
        <div className="detail">
          <div><b>Done when:</b> {task.done_condition}</div>
          <div><b>May write:</b> {task.writes.length ? task.writes.join(", ") : "anywhere in the project (so it runs alone)"}</div>
          {task.reason && <div><b>Last result:</b> {task.reason}</div>}
          {tools.length > 0 && <pre>{tools.join("\n")}</pre>}
          {artifact && <pre>{artifact}</pre>}
        </div>
      )}
    </>
  );
}

export function PlanPanel({ view }: { view: RunView }) {
  const [showRemoved, setShowRemoved] = useState(false);
  if (!view.tasks.length) {
    return <p className="empty">The Project Manager's plan appears here, grouped by what can run together.</p>;
  }
  const byId = new Map(view.tasks.map((t) => [t.id, t]));
  const removed = view.tasks.filter((t) => t.status === "superseded");
  const latest = view.plans[view.plans.length - 1];
  const stageList = stages(view.tasks);
  return (
    <div className="plan">
      {latest?.reason && (
        <p className="why"><b>{latest.replan ? "Why it changed:" : "Why this plan:"}</b> {latest.reason}</p>
      )}
      {view.plans.filter((p) => p.replan).map((p, i) => (
        <p key={p.seq} className="change">
          <b>Replan {i + 1}:</b>{" "}
          {p.added.length ? `added ${p.added.join("; ")}` : "no new tasks"}
          {p.removed.length ? ` · removed ${p.removed.join("; ")}` : ""}
        </p>
      ))}
      {stageList.map((st, i) => (
        <section key={st.level} className="stage-group">
          <h3>
            Stage {i + 1}
            <span>{i === 0 ? "runs first" : `after stage ${i}`}{st.tasks.length > 1 ? " · these can run together" : ""}</span>
          </h3>
          {st.tasks.map((t) => <TaskRow key={t.id} task={t} view={view} names={byId} />)}
        </section>
      ))}
      {removed.length > 0 && (
        <section className="stage-group">
          <button className="link" onClick={() => setShowRemoved(!showRemoved)}>
            {showRemoved ? "Hide" : "Show"} {removed.length} task{removed.length > 1 ? "s" : ""} removed by a replan
          </button>
          {showRemoved && removed.map((t) => <TaskRow key={t.id} task={t} view={view} names={byId} />)}
        </section>
      )}
      {view.guardrails.length > 0 && (
        <section className="stage-group">
          <h3>Guardrails that fired <span>{view.guardrails.length}</span></h3>
          {view.guardrails.map((g) => <p key={g.seq} className="guard">{guardrailText(g)}</p>)}
        </section>
      )}
    </div>
  );
}
