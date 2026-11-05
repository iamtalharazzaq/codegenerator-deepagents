/** Everything the screen shows is rebuilt from the run's event log by one reducer, so a live run, a finished run and
 * a reloaded page all go through the same code. */

export interface RunEvent {
  seq: number;
  ts: number;
  type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export type TaskStatus = "pending" | "in_progress" | "pass" | "fail" | "escalated" | "blocked" | "superseded";
export type RunStatus = "idle" | "running" | "passed" | "escalated" | "stopped" | "error" | "interrupted";
export type PmState = "idle" | "planning" | "replanning" | "approval" | "waiting" | "checking" | "done" | "stopped";

export interface TaskView {
  id: string;
  role: string;
  objective: string;
  inputs: string[];
  done_condition: string;
  depends_on: string[];
  writes: string[];
  status: TaskStatus;
  attempt: number;
  reason: string;
}

export type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "pm"; text: string; replan: boolean }
  | { kind: "result"; ok: boolean; final: boolean; role: string; text: string; reason: string }
  | { kind: "note"; text: string; tone: "info" | "warn" }
  | { kind: "done" | "stop"; title: string; text: string };

export interface GuardrailHit {
  seq: number;
  kind: string;
  reason: string;
  role?: string;
  path?: string;
}

export interface PlanChange {
  seq: number;
  replan: boolean;
  reason: string;
  added: string[];
  removed: string[];
}

export interface Pulse {
  id: number;
  role: string;
  back: boolean;
}

export interface RunView {
  runId: string | null;
  project: string;
  request: string;
  status: RunStatus;
  pm: PmState;
  check: "pass" | "fail" | null;
  tasks: TaskView[];
  chat: ChatItem[];
  toolLines: Record<string, string[]>;
  guardrails: GuardrailHit[];
  plans: PlanChange[];
  pulses: Pulse[];
  awaitingApproval: boolean;
  dispatches: number;
  replans: number;
  concurrency: number;
  zip: { files: number; partial: boolean } | null;
  secretBlock: GuardrailHit | null;
  finishedMessage: string;
  lastEvent: string;
  lastSeq: number;
}

export function emptyRun(): RunView {
  return {
    runId: null, project: "", request: "", status: "idle", pm: "idle", check: null, tasks: [], chat: [], toolLines: {},
    guardrails: [], plans: [], pulses: [], awaitingApproval: false, dispatches: 0, replans: 0, concurrency: 1,
    zip: null, secretBlock: null, finishedMessage: "", lastEvent: "", lastSeq: 0,
  };
}

const live = (t: TaskView) => t.status !== "superseded";
export const activeTasks = (s: RunView) => s.tasks.filter((t) => t.status === "in_progress");

function upsert(tasks: TaskView[], task: TaskView): TaskView[] {
  return tasks.some((t) => t.id === task.id) ? tasks.map((t) => (t.id === task.id ? task : t)) : [...tasks, task];
}

const clip = (s: string, n = 90) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

export function applyEvent(state: RunView, e: RunEvent): RunView {
  const s: RunView = { ...state, lastSeq: e.seq, lastEvent: describe(e) };
  const pulse = (role: string, back: boolean): Pulse[] => [...s.pulses, { id: e.seq, role, back }].slice(-12);
  switch (e.type) {
    case "run_started":
      return {
        ...emptyRun(), runId: e.run_id, project: e.project, request: e.request, status: "running",
        concurrency: e.concurrency ?? 1, lastSeq: e.seq, lastEvent: s.lastEvent, chat: [{ kind: "user", text: e.request }],
      };
    case "run_resumed":
      return {
        ...s, status: "running", finishedMessage: "", zip: null,
        chat: [...s.chat, { kind: "user", text: e.guidance || "Continue this run." }],
      };
    case "plan_started":
    case "replan_started":
      return {
        ...s, pm: e.type === "plan_started" ? "planning" : "replanning", check: null,
        replans: e.replans ?? s.replans,
      };
    case "plan_invalid":
      return { ...s, chat: [...s.chat, { kind: "note", tone: "warn", text: `The plan was rejected (${clip(e.error, 120)}). Asking again.` }] };
    case "plan_warning":
      return { ...s, chat: [...s.chat, { kind: "note", tone: "warn", text: e.message }] };
    case "plan_ready": {
      const before = new Set(s.tasks.map((t) => t.id));
      const tasks: TaskView[] = e.tasks;
      const added = tasks.filter((t) => !before.has(t.id) && live(t)).map((t) => t.objective);
      const removed = tasks.filter((t) => t.status === "superseded" && before.has(t.id)).map((t) => t.objective);
      const change: PlanChange = { seq: e.seq, replan: !!e.replan, reason: e.reason || "", added, removed };
      return {
        ...s, tasks, pm: "idle",
        plans: [...s.plans, change],
        chat: [...s.chat, {
          kind: "pm", replan: !!e.replan,
          text: e.reason || `${tasks.filter(live).length} tasks planned.`,
        }],
      };
    }
    case "plan_approval_requested":
      return { ...s, tasks: e.tasks, pm: "approval", awaitingApproval: true };
    case "plan_approved":
      return { ...s, awaitingApproval: false, pm: "idle" };
    case "plan_rejected":
      return { ...s, awaitingApproval: false, chat: [...s.chat, { kind: "note", tone: "info", text: "You rejected the plan." }] };
    case "task_started": {
      const task: TaskView = e.task;
      return {
        ...s, tasks: upsert(s.tasks, task), pm: "waiting", check: null, dispatches: s.dispatches + 1,
        toolLines: { ...s.toolLines, [task.id]: [] }, pulses: pulse(task.role, false),
      };
    }
    case "tool_call": {
      const line = `${e.tool} ${e.summary ?? ""}`.trim();
      const prev = s.toolLines[e.task_id] ?? [];
      return { ...s, toolLines: { ...s.toolLines, [e.task_id]: [...prev, line].slice(-8) } };
    }
    case "tool_result":
      return s;
    case "guardrail_hit": {
      const hit: GuardrailHit = { seq: e.seq, kind: e.kind, reason: e.reason ?? "", role: e.role, path: e.path };
      const secret = e.kind === "secret_scan" ? hit : s.secretBlock;
      return {
        ...s, guardrails: [...s.guardrails, hit], secretBlock: secret,
        chat: [...s.chat, { kind: "note", tone: "warn", text: `Guardrail: ${guardrailText(hit)}` }],
      };
    }
    case "task_blocked":
      return { ...s, tasks: s.tasks.map((t) => (t.id === e.task_id ? { ...t, status: "blocked", reason: e.reason } : t)) };
    case "task_finished": {
      const task: TaskView = e.task;
      const tasks = upsert(s.tasks, task);
      const stillActive = tasks.some((t) => t.status === "in_progress");
      const ok = e.verdict === "pass";
      return {
        ...s, tasks, check: ok ? "pass" : "fail", pm: stillActive ? "waiting" : "checking", pulses: pulse(task.role, true),
        chat: [...s.chat, {
          kind: "result", ok, final: !ok && !e.will_retry, role: task.role, text: ok ? "passed" : e.will_retry ? "failed" : "failed its last attempt",
          reason: task.reason,
        }],
      };
    }
    case "report_ready":
      return s;
    case "delivery_ready":
      return { ...s, zip: { files: e.files, partial: !!e.partial } };
    case "run_finished": {
      const status = e.status as RunStatus;
      const passed = status === "passed";
      const title = passed ? "Run passed" : status === "stopped" ? "Run stopped" : status === "error" ? "Run failed to finish" : "Run escalated";
      return {
        ...s, status, pm: passed ? "done" : "stopped", awaitingApproval: false, finishedMessage: e.message ?? "",
        tasks: s.tasks.map((t) => (t.status === "in_progress" ? { ...t, status: "fail" } : t)),
        chat: [...s.chat, { kind: passed ? "done" : "stop", title, text: finishText(e) }],
      };
    }
    default:
      return s;
  }
}

function finishText(e: RunEvent): string {
  const base = e.message ?? "";
  if (e.status === "passed") return `${base} The report and the zip are ready.`;
  if (e.status === "stopped") return base;
  return `${base} Nothing more will run until you decide: send a message to resume with guidance, or download what exists.`;
}

export function guardrailText(h: GuardrailHit): string {
  switch (h.kind) {
    case "write_blocked": return `a write to ${h.path ?? "a file"} was blocked (${h.reason}).`;
    case "task_timeout": return `a task ${h.reason}.`;
    case "status_overridden": return `a pass was overruled by the real result (${h.reason}).`;
    case "secret_scan": return `${h.reason}; the zip was not built.`;
    default: return h.reason || h.kind;
  }
}

function describe(e: RunEvent): string {
  const bits = [e.type];
  if (e.task?.role) bits.push(`role=${e.task.role}`);
  if (e.task_id) bits.push(`task=${e.task_id}`);
  if (e.tool) bits.push(`tool=${e.tool}`);
  if (e.verdict) bits.push(`status=${e.verdict}`);
  if (e.status && e.type === "run_finished") bits.push(`status=${e.status}`);
  return bits.join("  ");
}

/** The per-specialist state shown on the hub. */
export function nodeState(tasks: TaskView[], role: string): { cls: string; word: string } {
  const mine = tasks.filter((t) => t.role === role && live(t));
  if (!mine.length) return { cls: "", word: "idle" };
  const active = mine.filter((t) => t.status === "in_progress");
  if (active.length) return { cls: "active", word: `working · try ${active[0].attempt}` };
  if (mine.some((t) => t.status === "escalated")) return { cls: "esc", word: "escalated" };
  if (mine.some((t) => t.status === "blocked")) return { cls: "blocked", word: "blocked" };
  if (mine.some((t) => t.status === "fail")) return { cls: "fail", word: "failed" };
  const pending = mine.filter((t) => t.status === "pending");
  if (pending.length) return { cls: "queued", word: pending.some((t) => t.attempt) ? "retry queued" : `${pending.length} queued` };
  return { cls: "pass", word: `passed · ${mine.length}` };
}

export interface Stage {
  level: number;
  tasks: TaskView[];
}

/** Tasks grouped by how many tasks must pass before them; more than one task in a stage means they can run together. */
export function stages(tasks: TaskView[]): Stage[] {
  const open = tasks.filter(live);
  const byId = new Map(open.map((t) => [t.id, t]));
  const level = new Map<string, number>();
  const depth = (t: TaskView, seen: Set<string>): number => {
    const cached = level.get(t.id);
    if (cached !== undefined) return cached;
    if (seen.has(t.id)) return 0;
    seen.add(t.id);
    const deps = t.depends_on.map((d) => byId.get(d)).filter((d): d is TaskView => !!d);
    const value = deps.length ? 1 + Math.max(...deps.map((d) => depth(d, seen))) : 0;
    level.set(t.id, value);
    return value;
  };
  const groups = new Map<number, TaskView[]>();
  for (const t of open) {
    const l = depth(t, new Set());
    groups.set(l, [...(groups.get(l) ?? []), t]);
  }
  return [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([lvl, ts]) => ({ level: lvl, tasks: ts }));
}

export function replay(events: RunEvent[]): RunView {
  return events.reduce(applyEvent, emptyRun());
}
