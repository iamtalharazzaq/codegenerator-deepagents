/** Everything the screen shows is rebuilt from the run's event log by one reducer, so a live run, a finished run, a
 * reloaded page and the mock data all go through the same code. Selectors below turn that state into what the UI
 * needs to answer three questions at a glance: what state is the run in, what failed, and what to do next. */

import { roleLabel, SPECIALISTS } from "./roles";

export interface RunEvent {
  seq: number;
  ts: number;
  type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export type RunStatus = "idle" | "running" | "needs_approval" | "passed" | "escalated" | "stopped" | "error" | "interrupted";
export type PmState = "idle" | "planning" | "approval" | "waiting" | "checking" | "done" | "stopped";
/** The one status vocabulary used everywhere: chips, graph nodes, list rows. */
export type UiStatus = "passed" | "running" | "queued" | "blocked" | "failed" | "escalated" | "idle";

export interface GuardrailHit {
  seq: number;
  kind: string;
  reason: string;
  role?: string;
  path?: string;
  taskId?: string;
}

export interface TaskView {
  id: string;
  role: string;
  objective: string;
  inputs: string[];
  done_condition: string;
  depends_on: string[];
  writes: string[];
  status: string; // in_progress | pass | fail (older runs also: pending, escalated, blocked, superseded)
  attempt: number;
  reason: string;
  startSeq: number;
  endSeq: number | null;
  startTs: number;
  endTs: number | null;
  toolLines: string[];
  guardrails: GuardrailHit[];
}

export interface Todo {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface TodoChange {
  seq: number;
  why: string;
  added: string[];
  removed: string[];
  completed: string[];
}

/** Only what the person said and notes that belong to no task. Plans, results and the finish each have their own card. */
export type ChatItem =
  | { kind: "user"; seq: number; text: string }
  | { kind: "note"; seq: number; text: string; tone: "info" | "warn" };

export interface PmNote {
  seq: number;
  text: string;
}

export interface LogEntry {
  seq: number;
  ts: number;
  type: string;
  group: "task" | "tool" | "guard" | "run" | "plan";
  text: string;
  taskId?: string;
  role?: string;
  error?: boolean;
}

export interface Pulse {
  id: number;
  ts: number;
  role: string;
  back: boolean;
}

export interface Finished {
  status: RunStatus;
  reason: string;
  message: string;
  summary: string;
  seconds: number;
}

/** A file an agent wrote during the run, with the task that wrote it. */
export interface FileEntry {
  path: string;
  taskId: string;
  role: string;
}

export interface Review {
  round: number;
  summary: string;
  files: string[];
}

export interface RunView {
  runId: string | null;
  review: Review | null; // the finished work, waiting for the person to accept it or ask for changes
  project: string;
  request: string;
  status: RunStatus;
  pm: PmState;
  check: "pass" | "fail" | null;
  tasks: TaskView[];
  files: FileEntry[];
  todos: Todo[];
  todoChanges: TodoChange[];
  pmNotes: PmNote[];
  chat: ChatItem[];
  guardrails: GuardrailHit[]; // those with no task (dispatch cap, secret scan)
  pulses: Pulse[];
  awaitingApproval: boolean;
  dispatches: number;
  maxDispatches: number;
  concurrency: number;
  zip: { files: number; partial: boolean } | null;
  secretBlock: GuardrailHit | null;
  finished: Finished | null;
  log: LogEntry[];
  lastSaid: string;
  startedAt: number;
  endedAt: number | null;
  lastEvent: string;
  lastSeq: number;
}

export function emptyRun(): RunView {
  return {
    runId: null, project: "", request: "", status: "idle", pm: "idle", check: null, tasks: [], files: [], todos: [],
    review: null, todoChanges: [], pmNotes: [], chat: [], guardrails: [], pulses: [], awaitingApproval: false, dispatches: 0, maxDispatches: 20,
    concurrency: 1, zip: null, secretBlock: null, finished: null, log: [], lastSaid: "", startedAt: 0, endedAt: null,
    lastEvent: "", lastSeq: 0,
  };
}

const LOG_LIMIT = 800;
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const firstSentence = (s: string) => clip((s.trim().split(/(?<=[.!?])\s/)[0] ?? "").replace(/\s+/g, " "), 160);

function describeEvent(e: RunEvent): Pick<LogEntry, "group" | "text" | "taskId" | "role" | "error"> {
  switch (e.type) {
    case "task_started": return { group: "task", text: `${roleLabel(e.task.role)} started (try ${e.task.attempt}): ${clip(e.task.objective, 100)}`, taskId: e.task.id, role: e.task.role };
    case "task_finished": return { group: "task", text: `${roleLabel(e.task.role)} ${e.verdict === "pass" ? "passed" : "failed"}: ${clip(e.task.reason, 120)}`, taskId: e.task.id, role: e.task.role, error: e.verdict !== "pass" };
    case "tool_call": return { group: "tool", text: `${e.tool} ${e.summary ?? ""}`.trim(), taskId: e.task_id, role: e.role };
    case "tool_result": return { group: "tool", text: `→ ${e.summary ?? ""}`.trim(), taskId: e.task_id, role: e.role, error: !!e.error };
    case "guardrail_hit": return { group: "guard", text: `${e.kind}: ${e.reason ?? ""} ${e.path ?? ""}`.trim(), taskId: e.task_id, role: e.role, error: true };
    case "todos_updated": return { group: "plan", text: `to-do list updated (${e.todos.length} items)` };
    case "pm_said": return { group: "plan", text: `Project Manager: ${clip(e.text, 140)}` };
    case "run_finished": return { group: "run", text: `${e.status}: ${e.message ?? ""}`, error: e.status !== "passed" };
    default: return { group: "run", text: e.type.replace(/_/g, " ") };
  }
}

function upsertTask(tasks: TaskView[], next: TaskView): TaskView[] {
  return tasks.some((t) => t.id === next.id) ? tasks.map((t) => (t.id === next.id ? next : t)) : [...tasks, next];
}

function fromPayload(p: RunEvent["task"], prev: TaskView | undefined, e: RunEvent, finished: boolean): TaskView {
  return {
    id: p.id, role: p.role, objective: p.objective, inputs: p.inputs ?? [], done_condition: p.done_condition ?? "",
    depends_on: p.depends_on ?? [], writes: p.writes ?? [], status: p.status, attempt: p.attempt, reason: p.reason ?? "",
    startSeq: prev?.startSeq ?? e.seq, startTs: prev?.startTs ?? e.ts,
    endSeq: finished ? e.seq : prev?.endSeq ?? null, endTs: finished ? e.ts : prev?.endTs ?? null,
    toolLines: prev?.toolLines ?? [], guardrails: prev?.guardrails ?? [],
  };
}

function diffTodos(before: Todo[], after: Todo[], seq: number, why: string): TodoChange {
  const was = new Map(before.map((t) => [t.content, t.status]));
  const now = new Set(after.map((t) => t.content));
  return {
    seq, why,
    added: after.filter((t) => !was.has(t.content)).map((t) => t.content),
    removed: before.filter((t) => !now.has(t.content)).map((t) => t.content),
    completed: after.filter((t) => t.status === "completed" && was.get(t.content) !== undefined && was.get(t.content) !== "completed").map((t) => t.content),
  };
}

export function applyEvent(state: RunView, e: RunEvent): RunView {
  const d = describeEvent(e);
  const log = [...state.log, { seq: e.seq, ts: e.ts, type: e.type, ...d }].slice(-LOG_LIMIT);
  const s: RunView = { ...state, lastSeq: e.seq, lastEvent: `${e.type.replace(/_/g, " ")}${d.role ? `  ${roleLabel(d.role)}` : ""}`, log };
  const pulse = (role: string, back: boolean): Pulse[] => [...s.pulses, { id: e.seq, ts: e.ts, role, back }].slice(-12);
  switch (e.type) {
    case "run_started":
      return {
        ...emptyRun(), runId: e.run_id, project: e.project, request: e.request, status: "running", log, lastSeq: e.seq,
        lastEvent: s.lastEvent, concurrency: e.concurrency ?? 1, maxDispatches: e.max_dispatches ?? 20, startedAt: e.ts,
        chat: [{ kind: "user", seq: e.seq, text: e.request }],
      };
    case "run_resumed":
      return { ...s, status: "running", finished: null, endedAt: null, zip: null, chat: [...s.chat, { kind: "user", seq: e.seq, text: e.guidance || "Continue this run." }] };
    case "plan_started":
      return { ...s, pm: "planning", check: null };
    case "pm_said":
      return { ...s, lastSaid: e.text, pmNotes: [...s.pmNotes, { seq: e.seq, text: e.text }] };
    case "todos_updated": {
      const todos: Todo[] = e.todos;
      const change = s.todos.length === 0 ? null : diffTodos(s.todos, todos, e.seq, firstSentence(s.lastSaid));
      return { ...s, todos, pm: "idle", lastSaid: "", todoChanges: change ? [...s.todoChanges, change] : s.todoChanges };
    }
    case "plan_ready": { // runs recorded before the Project Manager became a deep agent
      const todos: Todo[] = (e.tasks as TaskView[]).filter((t) => t.status !== "superseded").map((t) => ({ content: `${roleLabel(t.role)}: ${t.objective}`, status: t.status === "pass" ? "completed" : "pending" }));
      return { ...s, todos, pm: "idle", pmNotes: e.reason ? [...s.pmNotes, { seq: e.seq, text: e.reason }] : s.pmNotes };
    }
    case "plan_approval_requested":
      return { ...s, todos: e.todos ?? s.todos, pm: "approval", awaitingApproval: true };
    case "plan_approved":
      return { ...s, awaitingApproval: false, pm: "idle" };
    case "plan_changes_requested": // the plan went back to the Project Manager; the revised plan comes back for approval
      return { ...s, awaitingApproval: false, pm: "planning", chat: [...s.chat, { kind: "user", seq: e.seq, text: `Changes to the plan: ${e.text}` }] };
    case "plan_rejected":
      return { ...s, awaitingApproval: false, chat: [...s.chat, { kind: "note", seq: e.seq, tone: "info", text: "You rejected the plan." }] };
    case "review_requested":
      return { ...s, review: { round: e.round ?? 1, summary: e.summary ?? "", files: e.files ?? [] }, pm: "approval" };
    case "review_accepted":
      return { ...s, review: null, pm: "idle" };
    case "review_changes_requested":
      return { ...s, review: null, pm: "planning", chat: [...s.chat, { kind: "user", seq: e.seq, text: e.text }] };
    case "pm_nudged":
      return { ...s, chat: [...s.chat, { kind: "note", seq: e.seq, tone: "warn", text: "The Project Manager ended without delegating anything, so it was asked once to delegate." }] };
    case "retry_requested":
      return { ...s, pm: "planning", chat: [...s.chat, { kind: "note", seq: e.seq, tone: "warn", text: `Re-planning (round ${e.round ?? 1}): failed work was sent back to the Project Manager to fix.\n${e.message ?? ""}` }] };
    case "plan_revised":
      return { ...s, chat: [...s.chat, { kind: "note", seq: e.seq, tone: "warn", text: e.message ?? "The Project Manager changed the plan after work started." }] };
    case "plan_warning":
      return { ...s, chat: [...s.chat, { kind: "note", seq: e.seq, tone: "warn", text: e.message }] };
    case "task_started": {
      const task = fromPayload(e.task, undefined, e, false);
      return { ...s, tasks: upsertTask(s.tasks, task), pm: "waiting", check: null, dispatches: s.dispatches + 1, pulses: pulse(task.role, false) };
    }
    case "tool_call": {
      const line = `${e.tool} ${e.summary ?? ""}`.trim();
      const writes = (e.tool === "write_file" || e.tool === "edit_file") && e.summary && !s.files.some((f) => f.path === e.summary);
      return {
        ...s,
        files: writes ? [...s.files, { path: String(e.summary), taskId: e.task_id, role: e.role }] : s.files,
        tasks: s.tasks.map((t) => (t.id === e.task_id ? { ...t, toolLines: [...t.toolLines, line].slice(-12) } : t)),
      };
    }
    case "tool_result":
      return s;
    case "guardrail_hit": {
      const hit: GuardrailHit = { seq: e.seq, kind: e.kind, reason: e.reason ?? "", role: e.role, path: e.path, taskId: e.task_id };
      const secret = e.kind === "secret_scan" ? hit : s.secretBlock;
      const owned = !!e.task_id && s.tasks.some((t) => t.id === e.task_id);
      const files = e.path ? s.files.filter((f) => !(f.taskId === e.task_id && f.path === e.path)) : s.files; // a blocked write wrote nothing
      if (owned) return { ...s, files, secretBlock: secret, tasks: s.tasks.map((t) => (t.id === e.task_id ? { ...t, guardrails: [...t.guardrails, hit] } : t)) };
      return { ...s, secretBlock: secret, guardrails: [...s.guardrails, hit], chat: [...s.chat, { kind: "note", seq: e.seq, tone: "warn", text: `Guardrail: ${guardrailText(hit)}` }] };
    }
    case "task_blocked":
      return s;
    case "task_finished": {
      const prev = s.tasks.find((t) => t.id === e.task.id);
      const task = fromPayload(e.task, prev, e, true);
      const tasks = upsertTask(s.tasks, task);
      const stillActive = tasks.some((t) => t.status === "in_progress");
      return {
        ...s, tasks, check: e.verdict === "pass" ? "pass" : "fail", pm: stillActive ? "waiting" : "checking", pulses: pulse(task.role, true),
      };
    }
    case "delivery_ready":
      return { ...s, zip: { files: e.files, partial: !!e.partial } };
    case "run_finished": {
      const status = e.status as RunStatus;
      const passed = status === "passed";
      const finished: Finished = { status, reason: e.reason ?? "", message: e.message ?? "", summary: e.summary ?? "", seconds: e.seconds ?? 0 };
      return {
        ...s, status, pm: passed ? "done" : "stopped", awaitingApproval: false, review: null, finished, endedAt: e.ts,
        tasks: s.tasks.map((t) => (t.status === "in_progress" ? { ...t, status: "fail", endSeq: e.seq, endTs: e.ts } : t)),
      };
    }
    default:
      return s;
  }
}

export function replay(events: RunEvent[]): RunView {
  return events.reduce(applyEvent, emptyRun());
}

export function guardrailText(h: GuardrailHit): string {
  switch (h.kind) {
    case "write_blocked": return `a write to ${h.path ?? "a file"} was blocked (${h.reason}).`;
    case "path_blocked": return `access to ${h.path ?? "a path"} was blocked (${h.reason}).`;
    case "task_timeout": return `a task ${h.reason}.`;
    case "agent_stuck": return `${h.reason}.`;
    case "dispatch_cap": return `the run hit its ${h.reason}.`;
    case "secret_scan": return `${h.reason}; the zip was not built.`;
    default: return h.reason || h.kind;
  }
}

// ------------------------------------------------------------------ selectors

export const isResumable = (status: RunStatus) => ["escalated", "stopped", "error", "interrupted"].includes(status);

/** The run's own status mapped onto the shared vocabulary (the label still says what really happened). */
export function runUi(status: RunStatus): UiStatus {
  switch (status) {
    case "running": return "running";
    case "needs_approval": return "blocked";
    case "passed": return "passed";
    case "escalated": return "escalated";
    case "error": return "failed";
    case "stopped": case "interrupted": return "blocked";
    default: return "idle";
  }
}

export const RUN_LABEL: Record<RunStatus, string> = {
  idle: "No run", running: "Running", needs_approval: "Needs approval", passed: "Passed", escalated: "Escalated", stopped: "Stopped", error: "Failed", interrupted: "Interrupted",
};

/** The latest delegation of each specialist decides how that specialist looks. */
export function latestTask(tasks: TaskView[], role: string): TaskView | undefined {
  return tasks.filter((t) => t.role === role).sort((a, b) => b.startSeq - a.startSeq)[0];
}

export function taskUi(view: RunView, task: TaskView): UiStatus {
  if (task.status === "in_progress") return "running";
  if (task.status === "pass") return "passed";
  const last = latestTask(view.tasks, task.role);
  return isResumable(view.status) && last?.id === task.id ? "escalated" : "failed";
}

export function roleOfTodo(content: string): string | null {
  const text = content.toLowerCase();
  return SPECIALISTS.map(([role]) => role).find((r) => text.includes(roleLabel(r).toLowerCase()) || text.includes(r.replace(/_/g, " "))) ?? null;
}

export function todoUi(view: RunView, todo: Todo): UiStatus {
  if (todo.status === "completed") return "passed";
  // The Project Manager does not always tick its last items. If that specialist's latest task passed, the item is
  // done: always once the run has passed, and while running for the item the Project Manager has marked in progress.
  const role = roleOfTodo(todo.content);
  const latest = role ? latestTask(view.tasks, role) : undefined;
  if (latest?.status === "pass" && (view.status === "passed" || todo.status === "in_progress")) return "passed";
  const ended = view.status !== "running" && view.status !== "idle";
  if (todo.status === "in_progress") {
    if (!ended) return "running";
    return latest && latest.status === "fail" ? "escalated" : "blocked";
  }
  if (view.status === "passed") return "idle";
  return ended ? "blocked" : "queued";
}

export function triesForTodo(view: RunView, todo: Todo): number {
  const role = roleOfTodo(todo.content);
  return role ? Math.max(0, ...view.tasks.filter((t) => t.role === role).map((t) => t.attempt)) : 0;
}

export function agentUi(view: RunView, role: string): UiStatus {
  const last = latestTask(view.tasks, role);
  if (last) return taskUi(view, last);
  const planned = view.todos.some((t) => roleOfTodo(t.content) === role && t.status !== "completed");
  if (!planned) return "idle";
  return todoUi(view, { content: roleLabel(role), status: "pending" });
}

export function progress(view: RunView): { done: number; total: number } {
  if (view.todos.length) return { done: view.todos.filter((t) => t.status === "completed").length, total: view.todos.length };
  const roles = new Set(view.tasks.map((t) => t.role));
  const done = [...roles].filter((r) => latestTask(view.tasks, r)?.status === "pass").length;
  return { done, total: roles.size };
}

export interface Blocker {
  ui: UiStatus;
  title: string;
  role?: string;
  taskId?: string;
  objective?: string;
  tries: number;
}

/** What stopped the run, or null. (Approval is a plan decision and lives in the plan card; the finish in the result card.) */
export function attention(view: RunView): Blocker | null {
  if (!isResumable(view.status) || view.awaitingApproval) return null;
  const failedLatest = [...new Set(view.tasks.map((t) => t.role))]
    .map((r) => latestTask(view.tasks, r))
    .filter((t): t is TaskView => !!t && t.status === "fail")
    .sort((a, b) => b.startSeq - a.startSeq)[0];
  const ui = runUi(view.status);
  if (failedLatest) {
    const tries = Math.max(...view.tasks.filter((t) => t.role === failedLatest.role).map((t) => t.attempt));
    return {
      ui, role: failedLatest.role, taskId: failedLatest.id, objective: failedLatest.objective, tries,
      title: `${roleLabel(failedLatest.role)} ${tries >= 2 ? `failed ${tries} times` : "failed"}`,
    };
  }
  return { ui, title: view.finished?.message || RUN_LABEL[view.status], tries: 0 };
}

export interface Wave {
  index: number;
  tasks: TaskView[];
  parallel: boolean;
  waitsFor: string[]; // roles of the previous wave
}

/** Delegations grouped by when they ran: those that overlapped in time are one parallel wave; each wave starts after
 * the previous one finished, which is how the Project Manager sequenced the work. */
export function waves(tasks: TaskView[]): Wave[] {
  const sorted = [...tasks].sort((a, b) => a.startSeq - b.startSeq);
  const out: Wave[] = [];
  let end = -Infinity;
  for (const t of sorted) {
    const last = out[out.length - 1];
    if (last && t.startSeq < end) {
      last.tasks.push(t);
      end = Math.max(end, t.endSeq ?? Infinity);
    } else {
      out.push({ index: out.length + 1, tasks: [t], parallel: false, waitsFor: last ? [...new Set(last.tasks.map((x) => x.role))] : [] });
      end = t.endSeq ?? Infinity;
    }
  }
  return out.map((w) => ({ ...w, parallel: w.tasks.length > 1 }));
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export type FeedItem =
  | { kind: "user"; seq: number; text: string }
  | { kind: "note"; seq: number; text: string; tone: "info" | "warn" }
  | { kind: "wave"; seq: number; tasks: TaskView[]; parallel: boolean };

/** The run as one chronological feed: what the person said, notes, and the delegations in the order they ran
 * (tasks that ran at the same time share one row). Plans, results and the finish are not repeated here. */
export function feed(view: RunView): FeedItem[] {
  const items: FeedItem[] = view.chat.map((c) => ({ ...c }));
  for (const w of waves(view.tasks)) items.push({ kind: "wave", seq: w.tasks[0].startSeq, tasks: w.tasks, parallel: w.parallel });
  return items.sort((a, b) => a.seq - b.seq);
}

/** The single "what is happening right now" line. */
export function nowLine(view: RunView): { ui: UiStatus; text: string } | null {
  if (view.status !== "running") return null;
  if (view.awaitingApproval) return { ui: "blocked", text: "Waiting for your approval of the plan" };
  if (view.review) return { ui: "blocked", text: "Waiting for your review before the zip is built" };
  const running = view.tasks.filter((t) => t.status === "in_progress");
  if (running.length) {
    const first = running[0];
    const tool = first.toolLines[first.toolLines.length - 1];
    const more = running.length > 1 ? ` and ${running.length - 1} more` : "";
    return { ui: "running", text: `${roleLabel(first.role)}${more} working${tool ? `: ${tool}` : ""}` };
  }
  if (view.pm === "planning" || view.todos.length === 0) return { ui: "running", text: "Project Manager is planning" };
  return { ui: "running", text: "Project Manager is reading the results and deciding what is next" };
}

/** Identical consecutive failures are shown once: later tries say "same as try N". */
export function repeatsEarlier(view: RunView, task: TaskView): number | null {
  if (task.status !== "fail" || !task.reason) return null;
  const earlier = view.tasks.filter((t) => t.role === task.role && t.attempt < task.attempt && t.reason === task.reason);
  return earlier.length ? earlier[0].attempt : null;
}

// ------------------------------------------------------------------ selectors for the redesigned screen

/** How many delegations were repeats of an earlier try. */
export const retries = (view: RunView): number => view.tasks.filter((t) => t.attempt > 1).length;

export type LogLevel = "info" | "warn" | "error";
/** A guardrail hit is a warning (the guardrail did its job); other failures are errors. */
export const levelOf = (e: LogEntry): LogLevel => (e.group === "guard" ? "warn" : e.error ? "error" : "info");

export const guardrailsOfRole = (view: RunView, role: string): GuardrailHit[] => view.tasks.filter((t) => t.role === role).flatMap((t) => t.guardrails);

/** Every guardrail hit of the run: those that belong to a task and those that belong to the run (dispatch cap, secret scan). */
export const allGuardrails = (view: RunView): GuardrailHit[] => [...view.tasks.flatMap((t) => t.guardrails), ...view.guardrails].sort((a, b) => a.seq - b.seq);

export type TimelineItem =
  | FeedItem
  | { kind: "pm"; seq: number; text: string; replan: boolean };

/** The activity timeline: what the person said, the Project Manager's reasoning (collapsed in the UI) and the delegations in order. */
export function timeline(view: RunView): TimelineItem[] {
  const notes: TimelineItem[] = view.pmNotes.map((n, i) => ({ kind: "pm", seq: n.seq, text: n.text, replan: i > 0 }));
  return [...feed(view), ...notes].sort((a, b) => a.seq - b.seq);
}

export interface LaneNode {
  key: string;
  role: string;
  task?: TaskView;
  ui: UiStatus;
  tries: number;
  /** the specialist this one is waiting on, when it cannot start */
  blockedBy?: string;
}

export interface Lane {
  index: number;
  label: string;
  parallel: boolean;
  nodes: LaneNode[];
}

/** The dependency swimlane: one stage per wave of delegations (a stage starts after the one above it finished), then a
 * last stage with the planned specialists that never started, each naming the specialist that blocked it. */
export function swimlane(view: RunView): Lane[] {
  const lanes: Lane[] = waves(view.tasks).map((w) => ({
    index: w.index,
    label: w.parallel ? `Stage ${w.index}: ${w.tasks.length} at once` : `Stage ${w.index}`,
    parallel: w.parallel,
    nodes: w.tasks.map((t) => ({ key: t.id, role: t.role, task: t, ui: taskUi(view, t), tries: t.attempt })),
  }));
  const started = new Set(view.tasks.map((t) => t.role));
  const waiting = [...new Set(view.todos.filter((t) => t.status !== "completed").map((t) => roleOfTodo(t.content)).filter((r): r is string => !!r && !started.has(r)))];
  if (waiting.length) {
    const blocker = attention(view)?.role;
    lanes.push({
      index: lanes.length + 1, label: `Stage ${lanes.length + 1}: not started`, parallel: waiting.length > 1,
      nodes: waiting.map((role) => ({ key: `wait-${role}`, role, ui: agentUi(view, role), tries: 0, blockedBy: blocker && blocker !== role ? blocker : undefined })),
    });
  }
  return lanes;
}

export interface FileNode {
  name: string;
  path: string;
  file?: FileEntry;
  children: FileNode[];
}

/** The written files as a folder tree (folders first, then files, both alphabetical). */
export function fileTree(files: string[], entries: FileEntry[] = []): FileNode[] {
  const root: FileNode = { name: "", path: "", children: [] };
  for (const raw of files) {
    const parts = raw.replace(/^\/+/, "").split("/").filter(Boolean);
    let at = root;
    parts.forEach((name, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let next = at.children.find((c) => c.name === name);
      if (!next) {
        next = { name, path, children: [] };
        at.children.push(next);
      }
      if (i === parts.length - 1) next.file = entries.find((f) => f.path.replace(/^\/+/, "") === path);
      at = next;
    });
  }
  const sort = (n: FileNode) => {
    n.children.sort((a, b) => Number(b.children.length > 0) - Number(a.children.length > 0) || a.name.localeCompare(b.name));
    n.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

/** Every file of the run: those written by agents, or (for a run waiting for review) the review's list. */
export function runFiles(view: RunView): string[] {
  const written = view.files.map((f) => f.path.replace(/^\/+/, ""));
  return [...new Set([...written, ...(view.review?.files ?? [])])];
}

export type RunGroup = "Today" | "Yesterday" | "Earlier";

/** Which sidebar group a run belongs to, by calendar day in the viewer's time zone. */
export function groupOf(createdAt: number, now = Date.now() / 1000): RunGroup {
  const day = (t: number) => new Date(t * 1000).setHours(0, 0, 0, 0);
  const diff = Math.round((day(now) - day(createdAt)) / 86_400_000);
  return diff <= 0 ? "Today" : diff === 1 ? "Yesterday" : "Earlier";
}

export function relativeTime(createdAt: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - createdAt);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  if (s < 7 * 86_400) return `${Math.round(s / 86_400)}d ago`;
  return new Date(createdAt * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** One entry per planned task (or per specialist when there is no plan yet), for the segmented progress bar. */
export function segments(view: RunView): UiStatus[] {
  if (view.todos.length) return view.todos.map((t) => todoUi(view, t));
  return [...new Set(view.tasks.map((t) => t.role))].map((r) => agentUi(view, r));
}

/** True while the agents are actually working. A run waiting for the person's plan decision or review is not working. */
export const isWorking = (view: RunView): boolean => view.status === "running" && !view.awaitingApproval && !view.review;

/** The chip for the top bar: a run waiting on a person is "Needs approval", not "Running". */
export function headline(view: RunView): { ui: UiStatus; label: string } {
  if (view.status === "running" && (view.review || view.awaitingApproval)) return { ui: "blocked", label: RUN_LABEL.needs_approval };
  return { ui: runUi(view.status), label: RUN_LABEL[view.status] };
}

const FILLER = /^(?:please|kindly|hey|hi|hello|can you|could you|would you|i (?:want|need|would like) (?:you )?to|i'd like (?:you )?to|let's|lets)\b[\s,:;-]*/i;
const TITLE_CHARS = 56;
const DANGLING = /\s(?:a|an|the|with|for|and|or|to|of|in|on|at|by|as|that|which|from|into)$/i;

/** A short heading for a run, made from its prompt: filler words dropped, the first sentence, cut at a word boundary.
 * The whole prompt stays available (sidebar tooltip, top of the Activity pane). */
export function runTitle(request: string, fallback = "Untitled run"): string {
  let text = request.replace(/\s+/g, " ").trim();
  for (let before = ""; before !== text; ) { before = text; text = text.replace(FILLER, ""); }
  text = (text.split(/(?<=[.!?])\s/)[0] ?? text).replace(/[.!?:;,\s]+$/, "");
  if (text.length > TITLE_CHARS) {
    const cut = text.slice(0, TITLE_CHARS);
    let words = cut.slice(0, Math.max(cut.lastIndexOf(" "), TITLE_CHARS / 2)).replace(/[,;:\s]+$/, "");
    while (DANGLING.test(words)) words = words.replace(DANGLING, "").replace(/[,;:\s]+$/, ""); // never end on "with an"
    text = `${words}…`;
  }
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : fallback;
}
