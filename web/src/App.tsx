import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type AppConfig, type RunRow } from "./api";
import { AgentPanel } from "./components/AgentPanel";
import { AttentionCard } from "./components/Attention";
import { Composer } from "./components/Composer";
import { EventDrawer } from "./components/EventDrawer";
import { Header } from "./components/Header";
import { HubView } from "./components/HubView";
import { PlanTab } from "./components/PlanTab";
import { ReportTab } from "./components/ReportTab";
import { RunList } from "./components/RunList";
import { StageView } from "./components/StageView";
import { Transcript } from "./components/Transcript";
import { mockFromUrl, mockRuns, mockView, type MockName } from "./mock";
import { attention } from "./model";
import { Card, useMedia } from "./ui/bits";
import { useRunStream } from "./useRunStream";

type NarrowTab = "chat" | "plan" | "graph";
const MOCK_BY_ID: Record<string, MockName> = { d2463e52: "escalated", a50a01c8: "passed", "0b53cbea": "escalated" };

export default function App() {
  const [mock, setMock] = useState<MockName | null>(() => mockFromUrl(window.location.search));
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunRow[]>(() => (mock ? mockRuns() : []));
  const [selected, setSelected] = useState<string | null>(() => (mock ? mockRuns()[0].run_id : null));
  const [restart, setRestart] = useState(0);
  const [panelTab, setPanelTab] = useState<"plan" | "report">("plan");
  const [graph, setGraph] = useState<"stages" | "hub">("stages");
  const [agent, setAgent] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [taskFilter, setTaskFilter] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [narrowTab, setNarrowTab] = useState<NarrowTab>("chat");
  const wide = useMedia("(min-width: 1024px)");

  const live = useRunStream(mock ? null : selected, restart);
  const mocked = useMemo(() => (mock ? mockView(mock) : null), [mock]);
  const view = mocked ?? live.view;
  const attn = attention(view);

  const refresh = useCallback(() => (mock ? Promise.resolve() : api.runs().then(setRuns).catch(() => undefined)), [mock]);
  useEffect(() => { api.config().then(setConfig).catch(() => undefined); }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => { void refresh(); }, [view.status, refresh]);
  useEffect(() => { if (view.status === "passed") setPanelTab("report"); }, [view.status]);

  const blocked = (): boolean => {
    if (!mock) return false;
    setNotice("This is mock data for design review, so actions are switched off.");
    return true;
  };
  const focusGuidance = useCallback(() => {
    setNarrowTab("chat");
    requestAnimationFrame(() => {
      const box = document.getElementById("guidance");
      box?.scrollIntoView({ block: "center" });
      box?.focus();
    });
  }, []);
  const fail = (e: unknown) => setNotice(e instanceof Error ? e.message : "Something went wrong.");

  const openLogs = (taskId?: string) => { setTaskFilter(taskId ?? ""); setDrawer(true); };
  const select = (id: string) => {
    if (mock) { setMock(MOCK_BY_ID[id] ?? "escalated"); setSelected(id); } else setSelected(id);
    setAgent(null); setPanelTab("plan");
  };
  const newRun = () => { setSelected(null); setAgent(null); setDraft(""); setPanelTab("plan"); focusGuidance(); };
  const start = async (text: string, approvePlan: boolean, concurrency: number) => {
    if (blocked()) return;
    setBusy(true);
    try {
      const r = await api.start({ request: text, plan_approval: approvePlan, concurrency });
      setSelected(r.run_id); setDraft(""); void refresh();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const resume = async (text: string) => {
    if (blocked() || !selected) return;
    setBusy(true);
    try {
      await api.resume(selected, text);
      setDraft(""); setRestart((n) => n + 1); setPanelTab("plan");
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const decide = (approved: boolean) => { if (!blocked() && selected) api.approve(selected, approved).catch(fail); };
  const cancel = () => { if (!blocked() && selected) api.cancel(selected).catch(fail); };

  const attentionCard = attn && (
    <AttentionCard
      view={view} attn={attn} compact={!wide} onApprove={decide} onGuidance={focusGuidance}
      onRetry={(text) => { setDraft(text); focusGuidance(); }} onLogs={openLogs} onOpenAgent={setAgent}
      onReport={() => { setPanelTab("report"); setNarrowTab("plan"); }}
    />
  );
  const chat = (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Conversation">
      <Transcript view={view} onOpenAgent={(role) => setAgent(role)} onLogs={openLogs} />
      <Composer view={view} config={config} selected={selected} value={draft} onChange={setDraft} busy={busy} onStart={start} onResume={resume} onCancel={cancel} onNew={newRun} />
    </Card>
  );
  const graphCard = (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2">
        <h2 className="font-semibold">{graph === "stages" ? "Stages" : "Agent hub"}</h2>
        <div role="group" aria-label="Graph view" className="flex overflow-hidden rounded-lg border border-control">
          {(["stages", "hub"] as const).map((g) => (
            <button key={g} type="button" aria-pressed={graph === g} onClick={() => setGraph(g)} className={`px-3 py-1 text-[13px] ${graph === g ? "bg-accent-bg font-semibold text-on-accent" : "text-fg-2 hover:bg-raised"}`}>{g === "stages" ? "Stages" : "Agent hub"}</button>
          ))}
        </div>
      </div>
      {graph === "stages" ? <StageView view={view} attn={attn} onOpen={(role) => setAgent(role)} /> : <HubView view={view} onOpen={setAgent} />}
    </Card>
  );
  const planCard = (
    <Card>
      <div role="tablist" aria-label="Plan and report" className="flex border-b border-line">
        {([["plan", "Plan"], ["report", "Report and zip"]] as const).map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={panelTab === id} onClick={() => setPanelTab(id)}
            className={`border-b-2 px-4 py-2 font-medium ${panelTab === id ? "border-accent text-fg" : "border-transparent text-fg-2 hover:text-fg"}`}>{label}</button>
        ))}
      </div>
      {panelTab === "plan" ? <PlanTab view={view} onOpenAgent={setAgent} /> : <ReportTab view={view} />}
    </Card>
  );

  const panel = agent && <AgentPanel view={view} role={agent} onClose={() => setAgent(null)} onLogs={(id) => { setAgent(null); openLogs(id); }} />;

  return (
    <div className={wide ? "flex h-dvh min-h-[640px] flex-col" : "flex min-h-dvh flex-col"}>
      <Header view={view} demo={!!config?.demo} mock={!!mock} onResume={focusGuidance} />
      {notice && (
        <div role="alert" className="flex items-center justify-between gap-3 bg-escalated-bg px-4 py-2 text-escalated">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} className="rounded-md border border-escalated/40 px-2 py-0.5 text-[13px]">Dismiss</button>
        </div>
      )}
      <main className={wide ? "min-h-0 flex-1 p-3" : "flex-1 p-3"}>
        {wide ? (
          <div className="grid h-full min-h-0 grid-cols-[230px_minmax(340px,420px)_minmax(0,1fr)] gap-3">
            <RunList runs={runs} selected={selected} onSelect={select} onNew={newRun} />
            <div className="flex min-h-0 flex-col">{chat}</div>
            <div className="relative min-h-0 overflow-hidden rounded-xl">
              <div className="flex h-full flex-col gap-3 overflow-y-auto pr-1">
                {attentionCard}
                {graphCard}
                {planCard}
              </div>
              {panel}
            </div>
          </div>
        ) : (
          <div className="relative flex flex-col gap-3">
            <label className="flex items-center gap-2 text-[13px] text-fg-2">Run
              <select value={selected ?? ""} onChange={(e) => (e.target.value ? select(e.target.value) : newRun())} className="min-w-0 flex-1 rounded-lg border border-control bg-surface px-2 py-1.5 text-fg">
                <option value="">New run</option>
                {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.request.slice(0, 48) || r.run_id} ({r.status})</option>)}
              </select>
            </label>
            {attentionCard}
            <div role="tablist" aria-label="Sections" className="flex rounded-lg border border-line bg-surface">
              {([["chat", "Chat"], ["plan", "Plan"], ["graph", "Graph"]] as const).map(([id, label]) => (
                <button key={id} role="tab" type="button" aria-selected={narrowTab === id} onClick={() => setNarrowTab(id)} className={`flex-1 px-3 py-2 font-medium ${narrowTab === id ? "bg-raised text-fg" : "text-fg-2"}`}>{label}</button>
              ))}
            </div>
            <div className={narrowTab === "chat" ? "flex h-[75dvh] flex-col" : "flex flex-col"}>
              {narrowTab === "chat" && chat}
              {narrowTab === "plan" && planCard}
              {narrowTab === "graph" && graphCard}
            </div>
            {panel}
          </div>
        )}
      </main>
      <EventDrawer view={view} open={drawer} onToggle={() => setDrawer(!drawer)} taskFilter={taskFilter} onTaskFilter={setTaskFilter} />
    </div>
  );
}
