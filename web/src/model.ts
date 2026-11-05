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

export type RunStatus = "idle" | "running" | "passed" | "escalated" | "stopped" | "error" | "interrupted";
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

export type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "pm"; text: string }
  | { kind: "todo"; text: string }
  | { kind: "result"; taskId: string; role: string; ok: boolean; attempt: number; reason: string }
  | { kind: "note"; text: string; tone: "info" | "warn" }
  | { kind: "run"; ok: boolean; title: string; text: string; summary: string };

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

export interface RunView {
  runId: string | null;
  project: string;
  request: string;
  status: RunStatus;
  pm: PmState;
  check: "pass" | "fail" | null;
  tasks: TaskView[];
  todos: Todo[];
  todoChanges: TodoChange[];
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
    runId: null, project: "", request: "", status: "idle", pm: "idle", check: null, tasks: [], todos: [],
    todoChanges: [], chat: [], guardrails: [], pulses: [], awaitingApproval: false, dispatches: 0, maxDispatches: 20,
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
        chat: [{ kind: "user", text: e.request }],
      };
    case "run_resumed":
      return { ...s, status: "running", finished: null, endedAt: null, zip: null, chat: [...s.chat, { kind: "user", text: e.guidance || "Continue this run." }] };
    case "plan_started":
      return { ...s, pm: "planning", check: null };
    case "pm_said":
      return { ...s, lastSaid: e.text, chat: [...s.chat, { kind: "pm", text: e.text }] };
    case "todos_updated": {
      const todos: Todo[] = e.todos;
      const first = s.todos.length === 0;
      const change = first ? null : diffTodos(s.todos, todos, e.seq, firstSentence(s.lastSaid));
      const text = first ? `Planned ${todos.length} item${todos.length === 1 ? "" : "s"}` : `Updated the plan${change && (change.added.length || change.removed.length) ? `: +${change.added.length} −${change.removed.length}` : ""}`;
      return { ...s, todos, pm: "idle", lastSaid: "", todoChanges: change ? [...s.todoChanges, change] : s.todoChanges, chat: [...s.chat, { kind: "todo", text }] };
    }
    case "plan_ready": { // runs recorded before the Project Manager became a deep agent
      const todos: Todo[] = (e.tasks as TaskView[]).filter((t) => t.status !== "superseded").map((t) => ({ content: `${roleLabel(t.role)}: ${t.objective}`, status: t.status === "pass" ? "completed" : "pending" }));
      return { ...s, todos, pm: "idle", chat: [...s.chat, ...(e.reason ? [{ kind: "pm" as const, text: e.reason }] : [])] };
    }
    case "plan_approval_requested":
      return { ...s, todos: e.todos ?? s.todos, pm: "approval", awaitingApproval: true };
    case "plan_approved":
      return { ...s, awaitingApproval: false, pm: "idle" };
    case "plan_rejected":
      return { ...s, awaitingApproval: false, chat: [...s.chat, { kind: "note", tone: "info", text: "You rejected the plan." }] };
    case "plan_warning":
      return { ...s, chat: [...s.chat, { kind: "note", tone: "warn", text: e.message }] };
    case "task_started": {
      const task = fromPayload(e.task, undefined, e, false);
      return { ...s, tasks: upsertTask(s.tasks, task), pm: "waiting", check: null, dispatches: s.dispatches + 1, pulses: pulse(task.role, false) };
    }
    case "tool_call": {
      const line = `${e.tool} ${e.summary ?? ""}`.trim();
      return { ...s, tasks: s.tasks.map((t) => (t.id === e.task_id ? { ...t, toolLines: [...t.toolLines, line].slice(-12) } : t)) };
    }
    case "tool_result":
      return s;
    case "guardrail_hit": {
      const hit: GuardrailHit = { seq: e.seq, kind: e.kind, reason: e.reason ?? "", role: e.role, path: e.path, taskId: e.task_id };
      const secret = e.kind === "secret_scan" ? hit : s.secretBlock;
      const owned = !!e.task_id && s.tasks.some((t) => t.id === e.task_id);
      if (owned) return { ...s, secretBlock: secret, tasks: s.tasks.map((t) => (t.id === e.task_id ? { ...t, guardrails: [...t.guardrails, hit] } : t)) };
      return { ...s, secretBlock: secret, guardrails: [...s.guardrails, hit], chat: [...s.chat, { kind: "note", tone: "warn", text: `Guardrail: ${guardrailText(hit)}` }] };
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
        chat: [...s.chat, { kind: "result", taskId: task.id, role: task.role, ok: e.verdict === "pass", attempt: task.attempt, reason: task.reason }],
      };
    }
    case "delivery_ready":
      return { ...s, zip: { files: e.files, partial: !!e.partial } };
    case "run_finished": {
      const status = e.status as RunStatus;
      const passed = status === "passed";
      const title = passed ? "Run passed" : status === "stopped" ? "Run stopped" : status === "error" ? "Run failed to finish" : "Run escalated";
      const finished: Finished = { status, reason: e.reason ?? "", message: e.message ?? "", summary: e.summary ?? "", seconds: e.seconds ?? 0 };
      return {
        ...s, status, pm: passed ? "done" : "stopped", awaitingApproval: false, finished, endedAt: e.ts,
        tasks: s.tasks.map((t) => (t.status === "in_progress" ? { ...t, status: "fail", endSeq: e.seq, endTs: e.ts } : t)),
        chat: [...s.chat, { kind: "run", ok: passed, title, text: e.message ?? "", summary: e.summary ?? "" }],
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
    case "passed": return "passed";
    case "escalated": return "escalated";
    case "error": return "failed";
    case "stopped": case "interrupted": return "blocked";
    default: return "idle";
  }
}

export const RUN_LABEL: Record<RunStatus, string> = {
  idle: "No run", running: "Running", passed: "Passed", escalated: "Escalated", stopped: "Stopped", error: "Failed", interrupted: "Interrupted",
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
  const ended = view.status !== "running" && view.status !== "idle";
  if (todo.status === "in_progress") {
    if (!ended) return "running";
    const role = roleOfTodo(todo.content);
    const last = role ? latestTask(view.tasks, role) : undefined;
    return last && last.status === "fail" ? "escalated" : "blocked";
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

export type Attention =
  | { kind: "approval"; title: string; detail: string[] }
  | { kind: "blocked"; ui: UiStatus; title: string; detail: string; role?: string; taskId?: string; objective?: string; tries: number; guardrails: number }
  | { kind: "done"; title: string; detail: string }
  | null;

/** The one thing the person needs to know or do next. */
export function attention(view: RunView): Attention {
  if (view.awaitingApproval) {
    return { kind: "approval", title: "Approve the plan to start", detail: view.todos.map((t) => t.content) };
  }
  if (view.status === "passed") {
    return { kind: "done", title: "Run passed", detail: view.finished?.summary || view.finished?.message || "All work finished." };
  }
  if (!isResumable(view.status)) return null;
  const failedLatest = [...new Set(view.tasks.map((t) => t.role))]
    .map((r) => latestTask(view.tasks, r))
    .filter((t): t is TaskView => !!t && t.status === "fail")
    .sort((a, b) => b.startSeq - a.startSeq)[0];
  const ui = runUi(view.status);
  if (failedLatest) {
    const tries = Math.max(...view.tasks.filter((t) => t.role === failedLatest.role).map((t) => t.attempt));
    return {
      kind: "blocked", ui, role: failedLatest.role, taskId: failedLatest.id, objective: failedLatest.objective, tries,
      title: `${roleLabel(failedLatest.role)} ${tries >= 2 ? `failed ${tries} times` : "failed"}`,
      detail: failedLatest.reason || view.finished?.message || "The task did not pass.",
      guardrails: view.tasks.filter((t) => t.role === failedLatest.role).reduce((n, t) => n + t.guardrails.length, 0),
    };
  }
  return { kind: "blocked", ui, title: RUN_LABEL[view.status], detail: view.finished?.message || "The run stopped.", tries: 0, guardrails: 0 };
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
