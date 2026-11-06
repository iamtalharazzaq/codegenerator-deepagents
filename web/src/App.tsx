import { motion } from "framer-motion";
import { FolderTree, GitBranch, LayoutDashboard, MessageSquareText, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type AppConfig, type Chat, type ChatRow, type ProjectRow, type RunRow } from "./api";
import { ActivityTimeline } from "./components/ActivityTimeline";
import { AgentDrawer } from "./components/AgentDrawer";
import { AttentionCard } from "./components/AttentionCard";
import { ChatPane } from "./components/ChatPane";
import { Composer } from "./components/Composer";
import { EventLogDrawer } from "./components/EventLogDrawer";
import { FilesPanel } from "./components/FilesPanel";
import { PlanStepper } from "./components/PlanStepper";
import { ReportDrawer } from "./components/ReportDrawer";
import { ResultCard, StatsRow } from "./components/ResultCard";
import { ReviewCard } from "./components/ReviewCard";
import { RevisionHistory } from "./components/RevisionHistory";
import { Sidebar } from "./components/Sidebar";
import { TeamView } from "./components/TeamView";
import { TopBar } from "./components/TopBar";
import { DataContext, serverSource, type DataSource } from "./data";
import { mockFromUrl, mockRuns, mockSource, mockView, type MockName } from "./mock";
import { attention, formatDuration, isResumable, latestTask, progress, retries, runFiles, runTitle } from "./model";
import { MOTION, STATUS } from "./theme/tokens";
import { useTheme } from "./theme/useTheme";
import { cx, useMedia, useNow } from "./ui/bits";
import { Drawer } from "./ui/Drawer";
import { Markdown } from "./ui/Markdown";
import { TabPanel, Tabs, type TabSpec } from "./ui/Tabs";
import { useRunStream } from "./useRunStream";

type PaneTab = "overview" | "team" | "files";
type MobileTab = "activity" | PaneTab;
const MOCK_BY_ID: Record<string, MockName> = { d2463e52: "escalated", a50a01c8: "passed" };
const MOCK_SELECTED: Record<MockName, string> = { escalated: "d2463e52", running: "d2463e52", planning: "d2463e52", approval: "d2463e52", passed: "a50a01c8", review: "a50a01c8" };
const RAIL_KEY = "orchestrator-rail";

function remembered(key: string, fallback: boolean): boolean {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === "1"; } catch { return fallback; }
}

export default function App() {
  const [mock, setMock] = useState<MockName | null>(() => mockFromUrl(window.location.search));
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunRow[] | null>(() => (mock ? mockRuns() : null));
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [chats, setChats] = useState<ChatRow[]>([]);
  const [talking, setTalking] = useState(false);
  const [chat, setChat] = useState<Chat | null>(null);
  const [chatOpts, setChatOpts] = useState({ finalReview: true, concurrency: 1 });
  const [thinking, setThinking] = useState(false);
  const [selected, setSelected] = useState<string | null>(() => (mock ? MOCK_SELECTED[mock] : null));
  const [restart, setRestart] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const [taskFilter, setTaskFilter] = useState("");
  const [draft, setDraft] = useState("");
  const [projectHint, setProjectHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<PaneTab>("overview");
  const [urlTab] = useState(() => new URLSearchParams(window.location.search).get("tab"));
  const [mobileTab, setMobileTab] = useState<MobileTab>("activity");
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const [agentRole, setAgentRole] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [rail, setRail] = useState(() => remembered(RAIL_KEY, false));
  const [theme, toggleTheme] = useTheme();
  const wide = useMedia("(min-width: 1024px)");
  const phone = useMedia("(max-width: 767px)");

  const live = useRunStream(mock ? null : selected, restart);
  const view = useMemo(() => (mock ? mockView(mock) : live.view), [mock, live.view]);
  const source: DataSource = useMemo(() => (mock ? mockSource(mock) : serverSource), [mock]);
  const blocker = attention(view);
  const now = useNow(view.status === "running");

  // ---------------------------------------------------------------- data
  const refresh = useCallback(() => {
    if (mock) return Promise.resolve();
    return Promise.all([api.runs().then(setRuns), api.projects().then(setProjects), api.chats().then(setChats)]).catch(() => undefined);
  }, [mock]);
  useEffect(() => { api.config().then(setConfig).catch(() => undefined); }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => { void refresh(); }, [view.status, refresh]);
  useEffect(() => { try { localStorage.setItem(RAIL_KEY, rail ? "1" : "0"); } catch { /* not remembered */ } }, [rail]);

  // The plan, the decision about it and the result all live on the Overview, so that is where a run opens.
  useEffect(() => {
    const linked = (["overview", "team", "files"] as const).find((t) => t === urlTab);
    setTab(linked ?? "overview");
  }, [selected, mock]); // eslint-disable-line react-hooks/exhaustive-deps

  // A run that needs a decision shows the place where the decision is made.
  useEffect(() => { if (view.review) setTab("overview"); }, [view.review]);
  useEffect(() => { if (view.awaitingApproval) setTab("overview"); }, [view.awaitingApproval]);

  // A small celebration the moment a run passes (live), or once when a passed mock is opened. Never on a plain reload.
  const lastStatus = useRef<Record<string, string>>({});
  const celebrated = useRef(new Set<string>());
  const [burst, setBurst] = useState<string | null>(null);
  useEffect(() => {
    const id = view.runId;
    if (!id) return;
    if (view.status === "passed" && !celebrated.current.has(id) && (mock || lastStatus.current[id] === "running")) {
      celebrated.current.add(id);
      setBurst(id);
    }
    lastStatus.current[id] = view.status;
  }, [view.runId, view.status, mock]);

  // ---------------------------------------------------------------- actions
  const blockedByMock = (): boolean => {
    if (!mock) return false;
    setNotice("This is mock data for design review, so actions are switched off.");
    return true;
  };
  const fail = (e: unknown) => setNotice(e instanceof Error ? e.message : "Something went wrong.");
  const focusGuidance = useCallback(() => {
    setMobileTab("activity");
    requestAnimationFrame(() => {
      const box = document.getElementById("guidance");
      box?.scrollIntoView({ block: "center" });
      box?.focus();
    });
  }, []);
  const openLogs = (taskId?: string) => { setTaskFilter(taskId ?? ""); setLogOpen(true); };
  const openAgentLogs = (role: string) => { setAgentRole(null); openLogs(latestTask(view.tasks, role)?.id); };
  const showTask = (id: string) => { setMobileTab("activity"); setFocus({ id, n: Date.now() }); };
  const select = (id: string) => {
    if (mock) { setMock(MOCK_BY_ID[id] ?? "escalated"); setSelected(id); } else setSelected(id);
    setTalking(false);
    setFocus(null);
    setMenuOpen(false);
  };
  const newRun = () => { setTalking(false); setSelected(null); setDraft(""); setProjectHint(""); setFocus(null); setMenuOpen(false); focusGuidance(); };
  const followUp = () => {
    const title = runTitle(view.request);
    setProjectHint(view.project);
    setSelected(null);
    setDraft(`Follow-up to "${title}": `);
    focusGuidance();
  };
  // ---------------------------------------------------------------- talk first
  const openChat = async (id: string) => {
    if (blockedByMock()) return;
    try { setChat(await api.chat(id)); setSelected(null); setTalking(true); setMenuOpen(false); } catch (e) { fail(e); }
  };
  const sendChat = async (text: string): Promise<boolean> => {
    setThinking(true);
    try {
      let current = chat;
      if (!current) { current = await api.newChat(); setChat(current); }
      // show the person's own message at once; the answer replaces it when it arrives
      setChat({ ...current, messages: [...current.messages, { role: "user", text, kind: "", ts: Date.now() / 1000 }] });
      const updated = await api.say(current.id, text);
      setChat(updated); void refresh();
      return true;
    } catch (e) { fail(e); setChat((c) => (c ? { ...c, messages: c.messages.slice(0, -1) } : c)); return false; } finally { setThinking(false); }
  };
  const planChat = async () => {
    if (!chat) return;
    setThinking(true);
    try { setChat(await api.draftPlan(chat.id)); } catch (e) { fail(e); } finally { setThinking(false); }
  };
  const buildChat = async (planApproval: boolean, finalReview: boolean) => {
    if (!chat) return;
    setBusy(true);
    try {
      const r = await api.build(chat.id, { plan_approval: planApproval, final_review: finalReview, concurrency: chatOpts.concurrency });
      setTalking(false); setSelected(r.run_id); void refresh();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  // Start: the request opens a conversation, and the Project Manager answers with a plan in key points.
  const start = async (text: string, concurrency: number, project: string | null, finalReview: boolean) => {
    if (blockedByMock()) return;
    setChatOpts({ finalReview, concurrency });
    setSelected(null); setTalking(true); setDraft(""); setThinking(true);
    setChat({ id: "", title: text, messages: [{ role: "user", text, kind: "", ts: Date.now() / 1000 }], project, run_ids: [] });
    try {
      const created = await api.newChat(project);
      setChat({ ...created, messages: [{ role: "user", text, kind: "", ts: Date.now() / 1000 }] });
      setChat(await api.say(created.id, text, true));
      void refresh();
    } catch (e) { fail(e); setTalking(false); setChat(null); setDraft(text); } finally { setThinking(false); }
  };
  const resume = async (text: string) => {
    if (blockedByMock() || !selected) return;
    setBusy(true);
    try {
      await api.resume(selected, text);
      setDraft(""); setRestart((n) => n + 1);
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const review = (accept: boolean, changes: string) => { if (!blockedByMock() && selected) api.review(selected, accept, changes).catch(fail); };
  const decide = (approved: boolean, feedback = "") => { if (!blockedByMock() && selected) api.approve(selected, approved, feedback).catch(fail); };
  const cancel = () => { if (!blockedByMock() && selected) api.cancel(selected).catch(fail); };
  const resumable = !!selected && isResumable(view.status);
  const retryNote = blocker?.objective ? `Retry: ${blocker.objective}. Keep what already passed.` : "";
  const prefill = (text: string) => { setDraft(text); focusGuidance(); };

  // ---------------------------------------------------------------- derived
  const { done, total } = progress(view);
  const elapsed = view.startedAt ? (view.endedAt ?? now) - view.startedAt : 0;
  const empty = view.status === "idle";
  const title = selected && !empty ? runTitle(view.request) : "New run";
  const stats = [
    { label: "Tasks", value: `${done}/${total}`, hint: total ? "passed" : undefined },
    { label: "Delegations", value: `${view.dispatches}/${view.maxDispatches}`, hint: "tasks handed to specialists (limit)" },
    { label: "Duration", value: formatDuration(elapsed) },
    { label: "Retries", value: String(retries(view)), hint: retries(view) ? "repeat tries" : "none needed" },
  ];
  const fileCount = runFiles(view).length;
  const tabs: TabSpec<PaneTab>[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard, badge: total ? `${done}/${total}` : undefined },
    { id: "team", label: "Team", icon: GitBranch },
    { id: "files", label: "Files", icon: FolderTree, badge: fileCount || undefined },
  ];

  const activity = talking && !selected ? (
    <ChatPane chat={chat} thinking={thinking || busy} onSend={sendChat} onPlan={() => void planChat()} onBuild={(a, r) => void buildChat(a, r)} defaultReview={chatOpts.finalReview} onOpenRun={select} onLeave={newRun} />
  ) : (
    <section aria-label="Activity" className="surface flex min-h-0 flex-1 flex-col overflow-hidden">
      <h2 className="sr-only">Activity</h2>
      <ActivityTimeline view={view} focus={focus} onLogs={openLogs} onOpenAgent={setAgentRole} onExample={prefill} />
      <Composer
        view={view} config={config} projects={projects} selected={selected} value={draft} onChange={setDraft} busy={busy} projectHint={projectHint} retryText={retryNote}
        onStart={start} onResume={resume} onCancel={cancel} onNew={newRun} onFollowUp={followUp} onRetry={prefill}
      />
    </section>
  );

  const attentionCard = blocker && (
    <AttentionCard view={view} blocker={blocker} onGuidance={focusGuidance} onRetry={prefill} onShow={() => blocker.taskId && showTask(blocker.taskId)} onLogs={() => openLogs(blocker.taskId)} />
  );
  const compactCard = blocker && (
    <AttentionCard view={view} blocker={blocker} compact onGuidance={focusGuidance} onRetry={prefill} onShow={() => undefined} onLogs={() => openLogs(blocker.taskId)} />
  );
  const panel = (id: PaneTab) => {
    switch (id) {
      case "overview": {
        const plan = !empty && (
          <>
            <PlanStepper view={view} onApprove={decide} onOpenRole={setAgentRole} onResume={resumable ? () => void resume("") : undefined} busy={busy} />
            <RevisionHistory view={view} />
          </>
        );
        const planFirst = view.status === "running" || view.awaitingApproval;
        const proposed = talking && !selected ? [...(chat?.messages ?? [])].reverse().find((m) => m.kind === "plan") : undefined;
        return (
          <div className="space-y-4">
            {proposed && (
              <section aria-labelledby="proposed-title" className="surface p-5">
                <h2 id="proposed-title" className="text-[17px] font-semibold tracking-tight">Proposed plan</h2>
                <p className="mt-1 text-[13px] text-fg-2">From your conversation with the Project Manager. Nothing has started: change it by talking, or use Build this.</p>
                <div className="mt-3"><Markdown text={proposed.text} /></div>
              </section>
            )}
            {view.review && <ReviewCard key={view.review.round} review={view.review} onDecide={review} />}
            {planFirst && plan}
            {empty ? (proposed ? null : <p className="surface p-5 text-fg-2">The plan, the result, the team and the files of a run show up here once it starts.</p>) : <ResultCard view={view} celebrate={burst === view.runId} onReport={() => setReportOpen(true)} />}
            {!empty && <StatsRow stats={stats} />}
            {!planFirst && plan}
          </div>
        );
      }
      case "team": return <TeamView view={view} onOpenAgent={setAgentRole} />;
      case "files": return <FilesPanel view={view} />;
    }
  };

  const pane = (
    <div className="-m-4 min-h-0 flex-1 overflow-y-auto">{/* the negative margin cancels the inner padding, so this pane lines up with the Activity card beside it */}
      <div className="space-y-4 p-4">
        {attentionCard}
        <div className="surface sticky top-4 z-10 overflow-hidden px-2 [background:color-mix(in_srgb,var(--surface)_92%,transparent)] backdrop-blur">
          <Tabs group="pane" label="Run details" tabs={tabs} value={tab} onChange={setTab} />
        </div>
        {tabs.map((t) => <TabPanel key={t.id} group="pane" id={t.id} active={tab === t.id}>{panel(t.id)}</TabPanel>)}
      </div>
    </div>
  );

  const mobileTabs: TabSpec<MobileTab>[] = [{ id: "activity", label: "Activity", icon: MessageSquareText }, ...tabs.map((t) => ({ ...t, badge: undefined }))];
  const phoneBody = (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="surface m-3 mb-0 px-1"><Tabs group="phone" label="Sections" tabs={mobileTabs} value={mobileTab} onChange={setMobileTab} fill /></div>
      {mobileTab === "activity" ? (
        <TabPanel group="phone" id="activity" active className="flex min-h-0 flex-1 flex-col p-3">
          {blocker && (
            <button type="button" onClick={() => setMobileTab("overview")} className={cx("mb-3 flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-[13px] font-semibold", STATUS[blocker.ui].chip)}>
              <TriangleAlert size={16} aria-hidden className="shrink-0" /><span className="min-w-0 flex-1 truncate">Attention needed: {blocker.title}</span><span className="shrink-0 underline">Details</span>
            </button>
          )}
          {activity}
        </TabPanel>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-4 p-3">
            {mobileTab === "overview" ? attentionCard : compactCard}
            {mobileTabs.filter((t) => t.id !== "activity").map((t) => <TabPanel key={t.id} group="phone" id={t.id} active={mobileTab === t.id}>{panel(t.id as PaneTab)}</TabPanel>)}
          </div>
        </div>
      )}
    </div>
  );

  const sidebarProps = { runs, selected, onSelect: select, onNew: newRun, chats, activeChat: talking && !selected ? chat?.id ?? null : null, onOpenChat: (id: string) => void openChat(id) };
  return (
    <DataContext.Provider value={source}>
      <div className="atmos flex h-dvh min-h-[560px] flex-col">
        <a href="#activity-pane" className="sr-only z-50 rounded-xl bg-surface px-4 py-2 focus:not-sr-only focus:absolute focus:left-3 focus:top-3">Skip to activity</a>
        <TopBar
          view={view} title={title} demo={!!config?.demo} mock={!!mock} theme={theme} wide={wide} logOpen={logOpen}
          onToggleTheme={toggleTheme} onMenu={() => setMenuOpen(true)} onResume={focusGuidance} onStop={cancel} onReport={() => setReportOpen(true)} onToggleLog={() => setLogOpen(!logOpen)}
        />
        {notice && (
          <div role="alert" className="flex items-center justify-between gap-3 border-b border-hairline bg-escalated-bg px-4 py-2 text-escalated">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="rounded-lg border border-escalated/40 px-3 py-1 text-[13px]">Dismiss</button>
          </div>
        )}
        <div className="flex min-h-0 flex-1">
          {wide && (
            <motion.aside initial={false} animate={{ width: rail ? 76 : 296 }} transition={MOTION.base} className="shrink-0 overflow-hidden border-r border-hairline bg-surface/60">
              <Sidebar {...sidebarProps} collapsed={rail} onToggle={() => setRail(!rail)} />
            </motion.aside>
          )}
          <main id="activity-pane" tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col outline-none">
            {phone ? phoneBody : (
              <div className={cx("grid min-h-0 flex-1 gap-4 p-4 pb-0 [&>*]:min-h-0", wide ? "grid-cols-[minmax(380px,5fr)_minmax(0,6fr)]" : "grid-cols-[minmax(320px,1fr)_minmax(0,1fr)]")}>
                <div className="flex min-h-0 flex-col pb-4">{activity}</div>
                <div className="flex min-h-0 flex-col pb-4">{pane}</div>
              </div>
            )}
            <EventLogDrawer view={view} open={logOpen} onToggle={() => setLogOpen(!logOpen)} taskFilter={taskFilter} onTaskFilter={setTaskFilter} />
          </main>
        </div>
      </div>
      {!wide && (
        <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Runs" side="left" width="max-w-[340px]">
          <div className="-mx-5 -my-4 h-full"><Sidebar {...sidebarProps} collapsed={false} /></div>
        </Drawer>
      )}
      <AgentDrawer view={view} role={agentRole} onClose={() => setAgentRole(null)} onLogs={openAgentLogs} />
      <ReportDrawer runId={view.runId} open={reportOpen} onClose={() => setReportOpen(false)} />
    </DataContext.Provider>
  );
}
