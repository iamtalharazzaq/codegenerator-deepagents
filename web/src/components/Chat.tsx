import { useEffect, useRef, useState } from "react";

import { api, type AppConfig } from "../api";
import type { ChatItem, RunView } from "../model";
import { roleLabel } from "../roles";

function Message({ m }: { m: ChatItem }) {
  switch (m.kind) {
    case "user": return <div className="m-user">{m.text}</div>;
    case "pm": return <div className="m-pm"><b>Project Manager{m.replan ? " (replan)" : ""}</b>{m.text}</div>;
    case "result":
      return (
        <div className="m-note">
          <i className={`badge ${m.ok ? "b-pass" : m.final ? "b-esc" : "b-fail"}`}>{m.ok ? "pass" : "fail"}</i>
          {roleLabel(m.role)} {m.text}
          <span>{m.reason}</span>
        </div>
      );
    case "note": return <div className={`m-flag ${m.tone}`}>{m.text}</div>;
    case "done": return <div className="m-done"><b>{m.title}</b>{m.text}</div>;
    case "stop": return <div className="m-stop"><b>{m.title}</b>{m.text}</div>;
  }
}

export function Chat({
  view, config, selected, resumable, onStarted, onResumed, onError,
}: {
  view: RunView;
  config: AppConfig | null;
  selected: string | null;
  resumable: boolean;
  onStarted: (id: string) => void;
  onResumed: () => void;
  onError: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [approvePlan, setApprovePlan] = useState(true);
  const [concurrency, setConcurrency] = useState(1);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [view.chat.length, view.awaitingApproval]);

  const running = view.status === "running";
  const send = async () => {
    const value = text.trim();
    if (busy || (!value && !resumable)) return;
    setBusy(true);
    try {
      if (resumable && selected) {
        await api.resume(selected, value);
        onResumed();
      } else {
        const r = await api.start({ request: value, plan_approval: approvePlan, concurrency });
        onStarted(r.run_id);
      }
      setText("");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };
  const decide = (approved: boolean) => {
    if (selected) api.approve(selected, approved).catch((e: Error) => onError(e.message));
  };
  const cancel = () => {
    if (selected) api.cancel(selected).catch((e: Error) => onError(e.message));
  };

  return (
    <section className="pane chat">
      <div className="msgs" aria-live="polite">
        {view.chat.length === 0 && (
          <div className="welcome">
            <b>What should be built?</b>
            <p>Describe the change. The Project Manager makes a to-do list, hands each task to the right specialist, checks every result, and replans if something fails.</p>
            {config?.demo && <p className="muted">Demo mode: a scripted model plays every role, so no LLM is needed.</p>}
          </div>
        )}
        {view.chat.map((m, i) => <Message key={i} m={m} />)}
        {view.awaitingApproval && (
          <div className="approve">
            <b>Approve this plan?</b>
            <span>Nothing starts until you decide. The plan is in the panel on the right.</span>
            <div><button className="btn primary" onClick={() => decide(true)}>Approve and start</button> <button className="btn" onClick={() => decide(false)}>Reject</button></div>
          </div>
        )}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        {!resumable && !running && (
          <div className="opts">
            <label><input type="checkbox" checked={approvePlan} onChange={(e) => setApprovePlan(e.target.checked)} /> Ask me to approve the plan</label>
            <label>At once <select value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select></label>
          </div>
        )}
        <textarea
          id="composer" rows={2} value={text} disabled={running}
          placeholder={running ? "The run is working…" : resumable ? "Guidance for the run (optional), then resume" : "Describe what to build"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
        />
        <div className="row-actions">
          {running ? <button type="button" className="btn" onClick={cancel}>Cancel run</button> : (
            <button className="btn primary" disabled={busy || (!text.trim() && !resumable)}>{resumable ? "Resume run" : "Start run"}</button>
          )}
        </div>
      </form>
    </section>
  );
}
