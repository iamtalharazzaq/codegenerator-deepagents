/** Mock runs for design review and tests: open the app with `?mock=escalated`, `?mock=running` or `?mock=passed`.
 * They are event logs, replayed through the same reducer as a live run, so what you see is what a real run produces. */

import type { RunRow } from "./api";
import { replay, type RunEvent, type RunView } from "./model";

const T0 = 1_760_000_000;

class Log {
  seq = 0;
  at = T0;
  events: RunEvent[] = [];
  emit(type: string, after: number, data: Record<string, unknown> = {}): RunEvent {
    this.at += after;
    const e: RunEvent = { seq: ++this.seq, ts: this.at, type, ...data };
    this.events.push(e);
    return e;
  }
}

type Spec = { id: string; role: string; objective: string; writes: string[]; attempt: number };
const task = (s: Spec, status: string, reason = "") => ({
  id: s.id, role: s.role, objective: s.objective, inputs: [], done_condition: "", depends_on: [], writes: s.writes,
  status, attempt: s.attempt, reason,
});

const TODO = {
  ba: "Business Analyst: write the requirements and acceptance criteria",
  pm: "Product Manager: write the user stories",
  sa: "Solution Architect: design the architecture",
  sa2: "Solution Architect: design the architecture (retry with a stricter objective)",
  be: "Backend Developer: implement the calculator logic",
  be2: "Backend Developer: implement the calculator logic in backend/ (retry)",
  fe: "Frontend Developer: build the keypad and display",
  qa: "QA Engineer: write and run the tests",
  ops: "DevOps Engineer: build and package the app",
};
type Status = "pending" | "in_progress" | "completed";
const todos = (items: [string, Status][]) => items.map(([content, status]) => ({ content, status }));

function work(log: Log, s: Spec, opts: { seconds: number; tools: [string, string][]; guard?: { path: string; reason: string }; fail?: string }) {
  log.emit("task_started", 2, { task: task(s, "in_progress") });
  let used = 0;
  for (const [tool, summary] of opts.tools) {
    log.emit("tool_call", 1, { task_id: s.id, role: s.role, tool, summary, error: false });
    log.emit("tool_result", 1, { task_id: s.id, role: s.role, tool, summary: "ok", error: false });
    used += 2;
  }
  if (opts.guard) {
    log.emit("guardrail_hit", 1, { kind: "write_blocked", task_id: s.id, role: s.role, tool: "write_file", path: opts.guard.path, reason: opts.guard.reason });
  }
  log.at += Math.max(1, opts.seconds - used - 3);
  const status = opts.fail ? "fail" : "pass";
  log.emit("task_finished", 1, { task: task(s, status, opts.fail ?? "done"), verdict: status, will_retry: !!opts.fail, artifact: `${s.id}.md`, tool_calls: opts.tools.length });
}

function escalated(): RunEvent[] {
  const log = new Log();
  log.emit("run_started", 0, { run_id: "d2463e52", project: "demo", request: "Make a calculator", plan_approval: true, concurrency: 1, max_dispatches: 20 });
  log.emit("plan_started", 1);
  log.emit("pm_said", 3, {
    text:
      "The workspace is empty, so there is no existing code to analyse. A calculator needs written requirements, user stories, an architecture, " +
      "a backend for the arithmetic, a frontend for the keypad and display, tests and a build. I will skip the Code Analyst and the Database Engineer " +
      "because nothing is stored. The Business Analyst and Product Manager go first so that every later specialist has written requirements to read.",
  });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "in_progress"], [TODO.pm, "pending"], [TODO.sa, "pending"], [TODO.be, "pending"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });
  log.emit("plan_approval_requested", 1, { todos: todos([[TODO.ba, "in_progress"], [TODO.pm, "pending"], [TODO.sa, "pending"], [TODO.be, "pending"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });
  log.emit("plan_approved", 12);

  work(log, { id: "2f64c404", role: "business_analyst", objective: "Define requirements and acceptance criteria for a standard calculator", writes: ["docs/requirements.md"], attempt: 1 },
    { seconds: 22, tools: [["write_file", "docs/requirements.md"]] });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "in_progress"], [TODO.sa, "pending"], [TODO.be, "pending"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });

  work(log, { id: "8ecdfdfb", role: "product_manager", objective: "Write user stories and prioritise the calculator features", writes: ["docs/user_stories.md"], attempt: 1 },
    { seconds: 17, tools: [["read_file", "docs/requirements.md"], ["write_file", "docs/user_stories.md"]] });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "completed"], [TODO.sa, "in_progress"], [TODO.be, "pending"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });

  work(log, { id: "b40e66e1", role: "solution_architect", objective: "Design the architecture: tech stack, components, data flow and interfaces", writes: ["docs/architecture.md"], attempt: 1 },
    { seconds: 143, tools: [["read_file", "docs/requirements.md"], ["read_file", "docs/user_stories.md"]], fail: "no status block found in the artifact" });
  log.emit("pm_said", 2, { text: "The Solution Architect finished without a status block, so I cannot tell whether the design is complete. I will retry it with the same specialist and a more specific objective." });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "completed"], [TODO.sa2, "in_progress"], [TODO.be, "pending"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });

  work(log, { id: "c51f77a2", role: "solution_architect", objective: "Design the architecture and end with a status block", writes: ["architecture_design.md"], attempt: 2 },
    { seconds: 74, tools: [["read_file", "docs/requirements.md"], ["write_file", "architecture_design.md"]], guard: { path: "calculator_app_architecture.md", reason: "outside this task's write scope (architecture_design.md)" } });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "completed"], [TODO.sa2, "completed"], [TODO.be, "in_progress"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });

  const recursion = "GraphRecursionError: Recursion limit of 60 reached without hitting a stop condition.";
  work(log, { id: "62d86f3a", role: "backend_developer", objective: "Implement the calculator logic", writes: ["server/**"], attempt: 1 },
    { seconds: 51, tools: [["read_file", "architecture_design.md"], ["ls", "path=/.git"]], guard: { path: "/server.js", reason: "outside this task's write scope (server/**)" }, fail: recursion });
  log.emit("pm_said", 2, { text: "The backend attempt failed with a step-limit error. That is an orchestration problem rather than a code problem, so I will retry it with a clearer write area." });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "completed"], [TODO.sa2, "completed"], [TODO.be2, "in_progress"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });

  work(log, { id: "d90a41be", role: "backend_developer", objective: "Implement the calculator logic in backend/", writes: ["backend/**"], attempt: 2 },
    { seconds: 130, tools: [["write_file", "backend/calculator/engine.js"], ["write_file", "backend/server.js"], ["read_file", "backend/server.js"]], guard: { path: "/calculation_engine.js", reason: "outside this task's write scope (backend/**)" }, fail: recursion });
  log.emit("run_finished", 1, {
    status: "escalated", reason: "pm_failed", message: "The Project Manager reported that the work did not finish.",
    tasks: { pass: 3, fail: 3 }, dispatches: 6, seconds: 421,
    summary: "The architecture is written, but the backend failed twice with a step-limit error, so the frontend, QA and DevOps work was not started. The backend files exist in backend/ and may be nearly complete.",
  });
  return log.events;
}

function passed(): RunEvent[] {
  const log = new Log();
  log.emit("run_started", 0, { run_id: "a50a01c8", project: "demo", request: "Create greet.py with greet(name) and a pytest test", concurrency: 1, max_dispatches: 20 });
  log.emit("plan_started", 1);
  log.emit("todos_updated", 3, { todos: todos([["Solution Architect: define the interface", "in_progress"], ["Backend Developer: write greet.py", "pending"], ["QA Engineer: write and run the tests", "pending"]]) });
  work(log, { id: "66e3a943", role: "solution_architect", objective: "Define the interface of greet()", writes: ["docs/interface.md"], attempt: 1 }, { seconds: 9, tools: [["write_file", "docs/interface.md"]] });
  log.emit("todos_updated", 1, { todos: todos([["Solution Architect: define the interface", "completed"], ["Backend Developer: write greet.py", "in_progress"], ["QA Engineer: write and run the tests", "pending"]]) });
  work(log, { id: "7cd0d475", role: "backend_developer", objective: "Implement greet(name)", writes: ["greet.py"], attempt: 1 }, { seconds: 12, tools: [["write_file", "greet.py"]] });
  log.emit("todos_updated", 1, { todos: todos([["Solution Architect: define the interface", "completed"], ["Backend Developer: write greet.py", "completed"], ["QA Engineer: write and run the tests", "in_progress"]]) });
  work(log, { id: "771890a1", role: "qa_engineer", objective: "Write and run pytest tests for greet()", writes: ["test_greet.py"], attempt: 1 }, { seconds: 31, tools: [["write_file", "test_greet.py"], ["run_tests", "pytest -q"]] });
  log.emit("todos_updated", 1, { todos: todos([["Solution Architect: define the interface", "completed"], ["Backend Developer: write greet.py", "completed"], ["QA Engineer: write and run the tests", "completed"]]) });
  log.emit("report_ready", 1, { path: "report.md" });
  log.emit("delivery_ready", 1, { path: "delivery.zip", files: 5, partial: false });
  log.emit("run_finished", 1, { status: "passed", reason: "all_passed", message: "All tasks passed.", tasks: { pass: 3 }, dispatches: 3, seconds: 58, summary: "greet.py returns \"Hello, <name>!\" and 15 pytest tests pass." });
  return log.events;
}

export type MockName = "escalated" | "running" | "passed";

export function mockEvents(name: MockName): RunEvent[] {
  if (name === "passed") return passed();
  const all = escalated();
  if (name === "escalated") return all;
  // running: stop while the second backend attempt is working
  const cut = all.findIndex((e) => e.type === "task_started" && e.task.id === "d90a41be");
  return all.slice(0, cut + 4);
}

export function mockView(name: MockName): RunView {
  return replay(mockEvents(name));
}

export function mockRuns(): RunRow[] {
  const row = (run_id: string, request: string, status: string, done: number, total: number, age: number): RunRow => ({
    run_id, project: "demo", request, status, reason: null, created_at: T0 - age, tasks_done: done, tasks_total: total,
  });
  return [
    row("d2463e52", "Make a calculator", "escalated", 3, 7, 0),
    row("a50a01c8", "Create greet.py with greet(name) and a pytest test", "passed", 3, 3, 3600),
    row("0b53cbea", "Hey", "stopped", 0, 1, 7200),
  ];
}

export function mockFromUrl(search: string): MockName | null {
  const value = new URLSearchParams(search).get("mock");
  return value === "escalated" || value === "running" || value === "passed" ? value : value === "" ? "escalated" : null;
}
