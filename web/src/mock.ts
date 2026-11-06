/** Mock runs for design review and tests: open the app with `?mock=escalated`, `?mock=running` or `?mock=passed`.
 * They are event logs, replayed through the same reducer as a live run, so what you see is what a real run produces. */

import type { RunRow } from "./api";
import type { DataSource } from "./data";
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
  be3: "Backend Developer: finish and verify backend/ (needs guidance)",
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
  log.emit("pm_said", 2, { text: "The backend failed twice with the same step-limit error, so retrying it a third time would repeat the failure. I am stopping here: the files in backend/ may already be close to done, and a person can say whether to finish them or start that area again." });
  log.emit("todos_updated", 1, { todos: todos([[TODO.ba, "completed"], [TODO.pm, "completed"], [TODO.sa2, "completed"], [TODO.be3, "in_progress"], [TODO.fe, "pending"], [TODO.qa, "pending"], [TODO.ops, "pending"]]) });
  log.emit("run_finished", 1, {
    status: "escalated", reason: "pm_failed", message: "The Project Manager reported that the work did not finish.",
    tasks: { pass: 3, fail: 3 }, dispatches: 6, seconds: 421,
    summary: "The architecture is written, but the backend failed twice with a step-limit error, so the frontend, QA and DevOps work was not started. The backend files exist in backend/ and may be nearly complete.",
  });
  return log.events;
}

const CALCULATOR_SUMMARY = [
  "## Summary",
  "",
  "A **responsive calculator** that runs in the browser with no build step. All three tasks passed on the first try and the 12 tests are green.",
  "",
  "### What was built",
  "",
  "- **Solution Architect:** a one-page design in `docs/architecture.md` and a `README.md` with run instructions.",
  "- **Frontend Developer:** the keypad and display (`index.html`, `styles.css`, `app.js`) on top of a pure `calculator.js` engine.",
  "- **QA Engineer:** 12 tests for the engine in `calculator.test.js`.",
  "",
  "### Run it",
  "",
  "1. Unzip the delivery.",
  "2. Open `index.html` in a browser.",
  "3. Run the tests with the command below.",
  "",
  "```",
  "node --test calculator.test.js",
  "# tests 12 | pass 12 | fail 0",
  "```",
  "",
  "### Decisions",
  "",
  "| Area | Decision |",
  "|---|---|",
  "| Division by zero | shows `Error`; `C` clears it |",
  "| Precision | results are rounded to 10 decimal places |",
].join("\n");

function passed(): RunEvent[] {
  const log = new Log();
  log.emit("run_started", 0, { run_id: "a50a01c8", project: "calculator-a50a01c8", request: "make a calculator", plan_approval: false, concurrency: 1, max_dispatches: 20 });
  log.emit("plan_started", 1);
  const items = (a: Status, b: Status, c: Status) => todos([["Solution Architect: design the calculator and write the README", a], ["Frontend Developer: build the keypad, display and engine", b], ["QA Engineer: write and run the engine tests", c]]);
  log.emit("todos_updated", 3, { todos: items("in_progress", "pending", "pending") });
  work(log, { id: "66e3a943", role: "solution_architect", objective: "Design the calculator: components, the engine interface and the README", writes: ["docs/architecture.md", "README.md"], attempt: 1 },
    { seconds: 8, tools: [["write_file", "docs/architecture.md"], ["write_file", "README.md"]] });
  log.emit("todos_updated", 1, { todos: items("completed", "in_progress", "pending") });
  work(log, { id: "7cd0d475", role: "frontend_developer", objective: "Build the keypad and display on top of a pure calculator engine", writes: ["index.html", "styles.css", "app.js", "calculator.js"], attempt: 1 },
    { seconds: 14, tools: [["write_file", "calculator.js"], ["write_file", "index.html"], ["write_file", "styles.css"], ["write_file", "app.js"]] });
  log.emit("todos_updated", 1, { todos: items("completed", "completed", "in_progress") });
  work(log, { id: "771890a1", role: "qa_engineer", objective: "Write and run tests for the calculator engine", writes: ["calculator.test.js"], attempt: 1 },
    { seconds: 11, tools: [["write_file", "calculator.test.js"], ["run_tests", "node --test calculator.test.js"]] });
  log.emit("todos_updated", 1, { todos: items("completed", "completed", "completed") });
  log.emit("report_ready", 1, { path: "report.md" });
  log.emit("delivery_ready", 1, { path: "delivery.zip", files: 7, partial: false });
  log.emit("run_finished", 1, { status: "passed", reason: "all_passed", message: "All tasks passed.", tasks: { pass: 3 }, dispatches: 3, seconds: 43, summary: CALCULATOR_SUMMARY });
  return log.events;
}

export type MockName = "escalated" | "running" | "passed" | "planning" | "approval" | "review";

function planning(withPlan: boolean): RunEvent[] {
  const log = new Log();
  log.emit("run_started", 0, { run_id: "e91b07c3", project: "calculator-in-python-e91b07c3", request: "Create a calculator in python only, with only arithmetic operators", concurrency: 1, max_dispatches: 20 });
  log.emit("plan_started", 1);
  log.emit("pm_said", 4, { text: "This is a single small module, so one specialist is enough. I will ask the Backend Developer for a Python file with the seven arithmetic operators and nothing else: no web server, no frontend and no design documents." });
  if (withPlan) {
    const items = todos([["Backend Developer: write calculator.py with + - * / // % ** only", "pending"], ["QA Engineer: write and run a pytest file for it", "pending"]]);
    log.emit("todos_updated", 2, { todos: items });
    log.emit("plan_approval_requested", 1, { todos: items });
  }
  return log.events;
}

/** Unfinished mocks end "now", so their elapsed time and live pulses look like a real run in progress. */
function endNow(events: RunEvent[]): RunEvent[] {
  const shift = Date.now() / 1000 - events[events.length - 1].ts;
  return events.map((e) => ({
    ...e, ts: e.ts + shift,
    ...(e.task ? { task: { ...e.task } } : {}),
  }));
}

function review(): RunEvent[] {
  const all = passed();
  const cut = all.findIndex((e) => e.type === "report_ready");
  const log = new Log();
  log.seq = all[cut - 1].seq; log.at = all[cut - 1].ts; log.events = all.slice(0, cut);
  log.emit("review_requested", 1, { round: 1, summary: CALCULATOR_SUMMARY, files: ["README.md", "app.js", "calculator.js", "calculator.test.js", "docs/architecture.md", "index.html", "styles.css"] });
  return log.events;
}

export function mockEvents(name: MockName): RunEvent[] {
  if (name === "review") return endNow(review());
  if (name === "planning") return endNow(planning(false));
  if (name === "approval") return endNow(planning(true));
  if (name === "passed") return passed();
  const all = escalated();
  if (name === "escalated") return all;
  // running: stop while the second backend attempt is working
  const cut = all.findIndex((e) => e.type === "task_started" && e.task.id === "d90a41be");
  return endNow(all.slice(0, cut + 4));
}

export function mockView(name: MockName): RunView {
  return replay(mockEvents(name));
}

export function mockRuns(): RunRow[] {
  const now = Date.now() / 1000;
  const row = (run_id: string, request: string, status: string, done: number, total: number, ageMinutes: number): RunRow => ({
    run_id, project: "demo", request, status, reason: null, created_at: now - ageMinutes * 60, tasks_done: done, tasks_total: total,
  });
  const long = "Build a command-line todo manager in Python with add, list, done and delete commands, JSON storage, colourised output and a full pytest suite";
  const ago = (h: number) => h * 60;
  const startOfToday = new Date().setHours(0, 0, 0, 0) / 1000;
  const sinceMidnight = Math.max(1, (now - startOfToday) / 60);
  return [
    row("d2463e52", "Make a calculator", "escalated", 3, 7, 2),
    row("a50a01c8", "make a calculator", "passed", 3, 3, Math.min(sinceMidnight - 1, 95)),
    row("0b53cbea", long, "stopped", 0, 1, sinceMidnight + 60),
    row("c7e1b02a", long, "passed", 5, 5, sinceMidnight + ago(26)),
    row("f10d9a44", "Add a password reset flow to the login page", "passed", 4, 4, sinceMidnight + ago(52)),
    row("9b2c33e7", "Create greet.py with greet(name) and a pytest test", "passed", 3, 3, sinceMidnight + ago(24 * 9)),
  ];
}

export function mockFromUrl(search: string): MockName | null {
  const value = new URLSearchParams(search).get("mock");
  const names = ["escalated", "running", "passed", "planning", "approval", "review"];
  return value !== null && names.includes(value) ? (value as MockName) : value === "" ? "escalated" : null;
}

// ------------------------------------------------------------------ what the server would return for reports, results and files

const FILES: Record<string, string> = {
  "calculator.js": [
    "// The engine: pure functions, no DOM, so it is easy to test.",
    "export function evaluate(a, op, b) {",
    "  if (op === \"/\" && b === 0) return \"Error\";",
    "  const result = { \"+\": a + b, \"-\": a - b, \"*\": a * b, \"/\": a / b }[op];",
    "  return Number(result.toFixed(10));",
    "}",
  ].join("\n"),
  "index.html": [
    "<!doctype html>",
    "<html lang=\"en\">",
    "  <head><meta charset=\"utf-8\" /><title>Calculator</title><link rel=\"stylesheet\" href=\"styles.css\" /></head>",
    "  <body>",
    "    <main class=\"calc\"><output id=\"display\">0</output><div id=\"keys\"></div></main>",
    "    <script type=\"module\" src=\"app.js\"></script>",
    "  </body>",
    "</html>",
  ].join("\n"),
  "calculator.test.js": [
    "import test from \"node:test\";",
    "import assert from \"node:assert/strict\";",
    "import { evaluate } from \"./calculator.js\";",
    "",
    "test(\"adds\", () => assert.equal(evaluate(2, \"+\", 3), 5));",
    "test(\"divides by zero without throwing\", () => assert.equal(evaluate(1, \"/\", 0), \"Error\"));",
    "test(\"rounds floating point noise\", () => assert.equal(evaluate(0.1, \"+\", 0.2), 0.3));",
  ].join("\n"),
  "styles.css": ".calc { max-width: 320px; margin: 4rem auto; font: 16px system-ui; }\n#display { display: block; padding: 1rem; text-align: right; font-size: 2rem; }",
  "app.js": "import { evaluate } from \"./calculator.js\";\n\nconst display = document.querySelector(\"#display\");\nlet left = null, op = null, typing = \"0\";",
  "README.md": "# Calculator\n\nOpen `index.html` in a browser. Run the tests with `node --test calculator.test.js`.",
  "docs/architecture.md": "# Architecture\n\nTwo layers: `calculator.js` is a pure engine, `app.js` wires it to the keypad and display.",
  "docs/requirements.md": "# Requirements\n\n- Add, subtract, multiply and divide\n- Clear and decimal point\n- Division by zero shows an error",
  "docs/user_stories.md": "# User stories\n\n1. As a user I can enter a sum with the keypad.\n2. As a user I can clear the display.",
  "architecture_design.md": "# Architecture\n\nA Node server exposes `POST /calculate`; the engine lives in `backend/calculator/engine.js`.",
  "backend/calculator/engine.js": "export function calculate(a, op, b) {\n  return { \"+\": a + b, \"-\": a - b, \"*\": a * b, \"/\": a / b }[op];\n}",
  "backend/server.js": "import http from \"node:http\";\nimport { calculate } from \"./calculator/engine.js\";",
};

const REPORT_TAIL = (v: RunView) => [
  "", "## Tasks", "", "| Role | Try | Result |", "|---|---|---|",
  ...v.tasks.map((t) => `| ${t.role.replace(/_/g, " ")} | ${t.attempt} | ${t.status === "pass" ? "pass" : "fail"} |`),
].join("\n");

/** The mock stand-in for the server's report, task result and file endpoints, so every drawer and preview has real content. */
export function mockSource(name: MockName): DataSource {
  const view = mockView(name);
  return {
    report: async () => `# Run ${view.runId}: ${view.status}\n\n**Request:** ${view.request}\n\n${view.finished?.summary ?? view.finished?.message ?? ""}${REPORT_TAIL(view)}`,
    artifact: async (_runId, artifactName) => {
      const task = view.tasks.find((t) => artifactName === `${t.id}.attempt${t.attempt}.md`);
      if (!task) throw new Error("The result file is not there.");
      return `## ${task.role.replace(/_/g, " ")}, try ${task.attempt}\n\n${task.objective}\n\n${task.status === "pass" ? "Finished. " : ""}${task.reason}`;
    },
    file: async (_runId, path) => {
      const body = FILES[path.replace(/^\/+/, "")];
      if (body === undefined) throw new Error("That file is not available.");
      return body;
    },
  };
}
