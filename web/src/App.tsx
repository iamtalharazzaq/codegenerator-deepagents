import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type AppConfig, type ProjectRow, type RunRow } from "./api";
import { BlockerCard } from "./components/Blocker";
import { Composer } from "./components/Composer";
import { EventDrawer } from "./components/EventDrawer";
import { Feed } from "./components/Feed";
import { Header } from "./components/Header";
import { HubView } from "./components/HubView";
import { NowLine } from "./components/NowLine";
import { PlanCard } from "./components/PlanCard";
import { ResultCard } from "./components/ResultCard";
import { RunList } from "./components/RunList";
import { mockFromUrl, mockRuns, mockView, type MockName } from "./mock";
import { attention, latestTask } from "./model";
import { Card, useMedia } from "./ui/bits";
import { useRunStream } from "./useRunStream";

type NarrowTab = "activity" | "plan" | "team";
const MOCK_BY_ID: Record<string, MockName> = { d2463e52: "escalated", a50a01c8: "passed", "0b53cbea": "escalated" };

export default function App() {
  const [mock, setMock] = useState<MockName | null>(() => mockFromUrl(window.location.search));
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunRow[]>(() => (mock ? mockRuns() : []));
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [selected, setSelected] = useState<string | null>(() => (mock ? mockRuns()[0].run_id : null));
  const [restart, setRestart] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const [taskFilter, setTaskFilter] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<NarrowTab>("activity");
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const wide = useMedia("(min-width: 1024px)");

  const live = useRunStream(mock ? null : selected, restart);
  const mocked = useMemo(() => (mock ? mockView(mock) : null), [mock]);
  const view = mocked ?? live.view;
  const blocker = attention(view);

  const refresh = useCallback(() => {
    if (mock) return Promise.resolve();
    return Promise.all([api.runs().then(setRuns), api.projects().then(setProjects)]).catch(() => undefined);
  }, [mock]);
  useEffect(() => { api.config().then(setConfig).catch(() => undefined); }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => { void refresh(); }, [view.status, refresh]);

  const blockedByMock = (): boolean => {
    if (!mock) return false;
    setNotice("This is mock data for design review, so actions are switched off.");
    return true;
  };
  const focusGuidance = useCallback(() => {
    setTab("activity");
    requestAnimationFrame(() => {
      const box = document.getElementById("guidance");
      box?.scrollIntoView({ block: "center" });
      box?.focus();
    });
  }, []);
  const fail = (e: unknown) => setNotice(e instanceof Error ? e.message : "Something went wrong.");
  const openLogs = (taskId?: string) => { setTaskFilter(taskId ?? ""); setDrawer(true); };
  const showTask = (id: string) => { setTab("activity"); setFocus({ id, n: Date.now() }); };
  const showRole = (role: string) => {
    const t = latestTask(view.tasks, role);
    if (t) showTask(t.id);
    else setNotice("That specialist has not been given work yet.");
  };
  const select = (id: string) => {
    if (mock) { setMock(MOCK_BY_ID[id] ?? "escalated"); setSelected(id); } else setSelected(id);
    setFocus(null);
  };
  const newRun = () => { setSelected(null); setDraft(""); setFocus(null); focusGuidance(); };
  const start = async (text: string, approvePlan: boolean, concurrency: number, project: string | null) => {
    if (blockedByMock()) return;
    setBusy(true);
    try {
      const r = await api.start({ request: text, plan_approval: approvePlan, concurrency, ...(project ? { project } : {}) });
      setSelected(r.run_id); setDraft(""); void refresh();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const resume = async (text: string) => {
    if (blockedByMock() || !selected) return;
    setBusy(true);
    try {
      await api.resume(selected, text);
      setDraft(""); setRestart((n) => n + 1);
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const decide = (approved: boolean) => { if (!blockedByMock() && selected) api.approve(selected, approved).catch(fail); };
  const cancel = () => { if (!blockedByMock() && selected) api.cancel(selected).catch(fail); };

  const blockerCard = blocker && (
    <BlockerCard blocker={blocker} onGuidance={focusGuidance} onRetry={(text) => { setDraft(text); focusGuidance(); }} onShow={() => blocker.taskId && showTask(blocker.taskId)} onLogs={() => openLogs(blocker.taskId)} />
  );
  const activity = (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Activity">
      <Feed view={view} focus={focus} onLogs={openLogs} />
      <Composer view={view} config={config} projects={projects} selected={selected} value={draft} onChange={setDraft} busy={busy} onStart={start} onResume={resume} onCancel={cancel} onNew={newRun} />
    </Card>
  );
  const plan = (
    <>
      <ResultCard view={view} />
      <PlanCard view={view} onApprove={decide} onOpenRole={showRole} />
    </>
  );
  const team = (
    <details open className="rounded-xl border border-line bg-surface">
      <summary className="px-4 py-3 font-semibold">Team</summary>
      <HubView view={view} onOpen={showRole} />
    </details>
  );

  return (
    <div className={wide ? "flex h-dvh min-h-[640px] flex-col" : "flex min-h-dvh flex-col"}>
      <Header view={view} demo={!!config?.demo} mock={!!mock} onResume={focusGuidance} />
      <NowLine view={view} />
      {notice && (
        <div role="alert" className="flex items-center justify-between gap-3 bg-escalated-bg px-4 py-2 text-escalated">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} className="rounded-md border border-escalated/40 px-2 py-0.5 text-[13px]">Dismiss</button>
        </div>
      )}
      <main className={wide ? "min-h-0 flex-1 p-3" : "flex-1 p-3"}>
        {wide ? (
          <div className="grid h-full min-h-0 grid-cols-[230px_minmax(360px,460px)_minmax(0,1fr)] gap-3">
            <RunList runs={runs} selected={selected} onSelect={select} onNew={newRun} />
            <div className="flex min-h-0 flex-col">{activity}</div>
            <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
              {blockerCard}
              {plan}
              {team}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-[13px] text-fg-2">Run
              <select value={selected ?? ""} onChange={(e) => (e.target.value ? select(e.target.value) : newRun())} className="min-w-0 flex-1 rounded-lg border border-control bg-surface px-2 py-1.5 text-fg">
                <option value="">New run</option>
                {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.request.slice(0, 48) || r.run_id} ({r.status})</option>)}
              </select>
            </label>
            {blockerCard}
            <div role="tablist" aria-label="Sections" className="flex rounded-lg border border-line bg-surface">
              {([["activity", "Activity"], ["plan", "Plan"], ["team", "Team"]] as const).map(([id, label]) => (
                <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)} className={`flex-1 px-3 py-2 font-medium ${tab === id ? "bg-raised text-fg" : "text-fg-2"}`}>{label}</button>
              ))}
            </div>
            <div className={tab === "activity" ? "flex h-[72dvh] flex-col" : "flex flex-col gap-3"}>
              {tab === "activity" && activity}
              {tab === "plan" && (view.status === "idle" && !view.todos.length ? <p className="p-2 text-fg-2">The plan appears here once a run starts.</p> : plan)}
              {tab === "team" && team}
            </div>
          </div>
        )}
      </main>
      <EventDrawer view={view} open={drawer} onToggle={() => setDrawer(!drawer)} taskFilter={taskFilter} onTaskFilter={setTaskFilter} />
    </div>
  );
}
