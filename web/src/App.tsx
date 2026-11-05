import { useCallback, useEffect, useState } from "react";

import { api, type AppConfig, type RunRow } from "./api";
import { Chat } from "./components/Chat";
import { Hub } from "./components/Hub";
import { PlanPanel } from "./components/PlanPanel";
import { Report } from "./components/Report";
import { RunList } from "./components/RunList";
import { useRunStream } from "./useRunStream";

const RESUMABLE = ["escalated", "stopped", "error", "interrupted"];

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [restart, setRestart] = useState(0);
  const [tab, setTab] = useState<"plan" | "report">("plan");
  const [error, setError] = useState<string | null>(null);
  const { view } = useRunStream(selected, restart);

  const refresh = useCallback(() => api.runs().then(setRuns).catch(() => undefined), []);
  useEffect(() => { api.config().then(setConfig).catch(() => undefined); }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => { void refresh(); }, [view.status, refresh]);
  useEffect(() => { if (view.status !== "running" && view.status !== "idle") setTab("report"); }, [view.status]);

  const done = view.tasks.filter((t) => t.status === "pass").length;
  const total = view.tasks.filter((t) => t.status !== "superseded").length;
  const resumable = !!selected && RESUMABLE.includes(view.status);

  return (
    <div className="app">
      <header className="bar">
        <h1>Orchestrator</h1>
        {config?.demo && <span className="tag">DEMO: scripted model</span>}
        {error && <button className="alert" onClick={() => setError(null)} role="alert">{error} (dismiss)</button>}
      </header>
      <main className="main">
        <RunList runs={runs} selected={selected} onSelect={(id) => { setSelected(id); setTab("plan"); }} onNew={() => { setSelected(null); setTab("plan"); }} />
        <Chat
          view={view} config={config} selected={selected} resumable={resumable}
          onStarted={(id) => { setSelected(id); setTab("plan"); void refresh(); }}
          onResumed={() => { setRestart((n) => n + 1); setTab("plan"); }}
          onError={setError}
        />
        <section className="pane board">
          <div className="board-head">
            <span className={`pill ${view.status}`}>{view.status === "idle" ? "no run" : view.status}</span>
            <span className="stat">tasks <b>{done}/{total}</b></span>
            <span className="stat">dispatches <b>{view.dispatches}</b> of 20</span>
            <span className="stat">at once <b>{view.concurrency}</b></span>
            {view.runId && <span className="stat">run <b>{view.runId}</b></span>}
          </div>
          <div className="stage"><Hub view={view} /></div>
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "plan"} onClick={() => setTab("plan")}>Plan</button>
            <button role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>Report and zip</button>
          </div>
          <div className="tasks">{tab === "plan" ? <PlanPanel view={view} /> : <Report view={view} resumable={resumable} />}</div>
          <div className="ticker"><b>event</b>  {view.lastEvent || "waiting for a run"}</div>
        </section>
      </main>
    </div>
  );
}
