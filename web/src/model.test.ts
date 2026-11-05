import { describe, expect, it } from "vitest";

import { mockEvents, mockView } from "./mock";
import {
  agentUi, applyEvent, attention, emptyRun, feed, formatDuration, nowLine, progress, repeatsEarlier, replay, roleOfTodo, runUi, taskUi, todoUi, waves, type RunEvent,
} from "./model";

let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}, ts = 1000 + seq): RunEvent => ({ seq: ++seq, ts, type, ...data });
const mk = (id: string, role: string, status: string, attempt = 1, reason = "") => ({
  id, role, objective: `do ${id}`, inputs: [], done_condition: "", depends_on: [], writes: [], status, attempt, reason,
});

describe("the escalated example (the screen in the design brief)", () => {
  const view = mockView("escalated");

  it("reads as an escalated run with 3 of 7 tasks and 6 of 20 dispatches", () => {
    expect(view.status).toBe("escalated");
    expect(runUi(view.status)).toBe("escalated");
    expect(progress(view)).toEqual({ done: 3, total: 7 });
    expect([view.dispatches, view.maxDispatches]).toEqual([6, 20]);
    expect(view.runId).toBe("d2463e52");
  });

  it("names the blocker once: which agent and how many tries (the reason stays on its task card)", () => {
    const a = attention(view);
    expect(a).toMatchObject({ role: "backend_developer", title: "Backend Developer failed 2 times", tries: 2, ui: "escalated" });
    expect(a?.taskId).toBe(view.tasks.filter((t) => t.role === "backend_developer")[1].id);
  });

  it("does not repeat an identical error: the second try says it is the same as the first", () => {
    const [first, second] = view.tasks.filter((t) => t.role === "backend_developer");
    expect(repeatsEarlier(view, first)).toBeNull();
    expect(repeatsEarlier(view, second)).toBe(1);
    const sa = view.tasks.filter((t) => t.role === "solution_architect");
    expect(repeatsEarlier(view, sa[0])).toBeNull(); // a pass is never a repeat
  });

  it("attaches guardrail hits to the task they belong to instead of the conversation", () => {
    const hits = view.tasks.map((t) => [t.role, t.attempt, t.guardrails.length]);
    expect(hits).toContainEqual(["backend_developer", 1, 1]);
    expect(hits).toContainEqual(["backend_developer", 2, 1]);
    expect(hits).toContainEqual(["solution_architect", 2, 1]);
    expect(view.guardrails).toEqual([]);
    expect(view.chat.some((c) => c.kind === "note")).toBe(false); // no floating banners
  });

  it("gives every specialist one status from the shared vocabulary", () => {
    expect(agentUi(view, "business_analyst")).toBe("passed");
    expect(agentUi(view, "solution_architect")).toBe("passed"); // failed once, passed on the retry
    expect(agentUi(view, "backend_developer")).toBe("escalated");
    expect(agentUi(view, "frontend_developer")).toBe("blocked"); // planned, never started, run stopped
    expect(agentUi(view, "qa_engineer")).toBe("blocked");
    expect(agentUi(view, "code_analyst")).toBe("idle"); // not in the plan
    const sa = view.tasks.filter((t) => t.role === "solution_architect");
    expect(sa.map((t) => taskUi(view, t))).toEqual(["failed", "passed"]);
    const be = view.tasks.filter((t) => t.role === "backend_developer");
    expect(be.map((t) => taskUi(view, t))).toEqual(["failed", "escalated"]);
  });

  it("maps plan items to statuses and tries", () => {
    const statuses = view.todos.map((t) => todoUi(view, t));
    expect(statuses).toEqual(["passed", "passed", "passed", "escalated", "blocked", "blocked", "blocked"]);
    expect(roleOfTodo("Backend Developer: implement it")).toBe("backend_developer");
    expect(roleOfTodo("write the docs")).toBeNull();
  });

  it("keeps the plan's revisions as diffs with a one-line reason, and does not repeat the whole plan", () => {
    const withText = view.todoChanges.filter((c) => c.added.length || c.removed.length);
    expect(withText).toHaveLength(2);
    expect(withText[0].added).toEqual(["Solution Architect: design the architecture (retry with a stricter objective)"]);
    expect(withText[0].removed).toEqual(["Solution Architect: design the architecture"]);
    expect(withText[0].why).toBe("The Solution Architect finished without a status block, so I cannot tell whether the design is complete.");
    expect(withText[1].added[0]).toContain("(retry)");
    expect(view.todoChanges.flatMap((c) => c.completed)).toHaveLength(3);
  });

  it("builds one chronological feed: the request, then each delegation, with no plan, result or finish lines", () => {
    const items = feed(view);
    expect(items[0]).toMatchObject({ kind: "user", text: "Make a calculator" });
    expect(items.filter((i) => i.kind === "wave")).toHaveLength(6);
    expect(items.map((i) => i.seq)).toEqual([...items.map((i) => i.seq)].sort((a, b) => a - b));
    expect(items.every((i) => i.kind === "user" || i.kind === "wave")).toBe(true); // nothing repeated as chat lines
  });

  it("orders the work into stages that each wait for the one before", () => {
    const w = waves(view.tasks);
    expect(w.map((x) => x.tasks.map((t) => `${t.role}#${t.attempt}`))).toEqual([
      ["business_analyst#1"], ["product_manager#1"], ["solution_architect#1"], ["solution_architect#2"], ["backend_developer#1"], ["backend_developer#2"],
    ]);
    expect(w[1].waitsFor).toEqual(["business_analyst"]);
    expect(w.every((x) => !x.parallel)).toBe(true);
  });

  it("keeps the Project Manager's reasoning with the plan, not in the feed", () => {
    expect(view.pmNotes).toHaveLength(3);
    expect(view.pmNotes[0].text.length).toBeGreaterThan(300); // long on purpose: the UI clamps it to 3 lines
    expect(feed(view).some((i) => "text" in i && i.text.includes("workspace is empty"))).toBe(false);
  });

  it("is replayable from its events alone", () => {
    expect(replay(mockEvents("escalated"))).toEqual(view);
  });
});

describe("the other examples", () => {
  it("running: nothing is blocked, the backend is working, and one line says so", () => {
    const view = mockView("running");
    expect(view.status).toBe("running");
    expect(attention(view)).toBeNull();
    expect(nowLine(view)).toEqual({ ui: "running", text: expect.stringContaining("Backend Developer working") });
    expect(agentUi(view, "backend_developer")).toBe("running");
    expect(view.pm).toBe("waiting");
    expect(view.dispatches).toBe(6);
  });

  it("passed: nothing is blocked; the zip and summary are on the result card", () => {
    const view = mockView("passed");
    expect(attention(view)).toBeNull();
    expect(nowLine(view)).toBeNull();
    expect(view.finished?.summary).toContain("15 pytest tests pass");
    expect(view.zip).toEqual({ files: 5, partial: false });
    expect(progress(view)).toEqual({ done: 3, total: 3 });
  });
});

describe("reducer", () => {
  it("shows the planning while it happens, then holds the first delegation for approval in the plan", () => {
    seq = 0;
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_started")]);
    expect(nowLine(s)).toEqual({ ui: "running", text: "Project Manager is planning" });
    expect(s.todos).toEqual([]); // the plan card shows its planning state until the list arrives
    s = applyEvent(s, ev("pm_said", { text: "Two pieces of work." }));
    expect(s.pmNotes.map((n) => n.text)).toEqual(["Two pieces of work."]);
    s = applyEvent(s, ev("plan_approval_requested", { todos: [{ content: "Backend Developer: build", status: "pending" }] }));
    expect(s.awaitingApproval).toBe(true);
    expect(nowLine(s)?.text).toBe("Waiting for your approval of the plan");
    expect(attention(s)).toBeNull(); // the approval buttons are part of the plan card, not a second card
    s = applyEvent(s, ev("plan_approved"));
    expect(s.awaitingApproval).toBe(false);
  });

  it("feed: tasks that ran at the same time share one row, and what the person said is interleaved in order", () => {
    seq = 0;
    const s = replay([
      ev("run_started", { run_id: "r", project: "p", request: "x" }),
      ev("task_started", { task: mk("a", "database_engineer", "in_progress") }),
      ev("task_started", { task: mk("b", "backend_developer", "in_progress") }),
      ev("task_finished", { task: mk("a", "database_engineer", "pass"), verdict: "pass" }),
      ev("task_finished", { task: mk("b", "backend_developer", "pass"), verdict: "pass" }),
      ev("run_finished", { status: "escalated", reason: "pm_failed", message: "stopped" }),
      ev("run_resumed", { guidance: "go on" }),
    ]);
    const items = feed(s);
    expect(items.map((i) => i.kind)).toEqual(["user", "wave", "user"]);
    expect(items[1]).toMatchObject({ kind: "wave", parallel: true });
  });

  it("runs delegations side by side as one parallel stage", () => {
    seq = 0;
    const s = replay([
      ev("run_started", { run_id: "r", project: "p", request: "x" }),
      ev("task_started", { task: mk("a", "database_engineer", "in_progress") }),
      ev("task_started", { task: mk("b", "backend_developer", "in_progress") }),
      ev("task_finished", { task: mk("a", "database_engineer", "pass"), verdict: "pass" }),
      ev("task_finished", { task: mk("b", "backend_developer", "pass"), verdict: "pass" }),
      ev("task_started", { task: mk("c", "qa_engineer", "in_progress") }),
    ]);
    const w = waves(s.tasks);
    expect(w.map((x) => [x.parallel, x.tasks.length])).toEqual([[true, 2], [false, 1]]);
    expect(w[1].waitsFor.sort()).toEqual(["backend_developer", "database_engineer"]);
    expect(s.pm).toBe("waiting");
  });

  it("a run cut off mid-task marks the running task failed", () => {
    seq = 0;
    const s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("task_started", { task: mk("a", "qa_engineer", "in_progress") }), ev("run_finished", { status: "error", reason: "error", message: "boom" })]);
    expect(s.tasks[0].status).toBe("fail");
    expect(runUi(s.status)).toBe("failed");
  });

  it("a resumed run goes back to running, drops the finish, and shows the guidance in the chat", () => {
    seq = 0;
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("run_finished", { status: "escalated", reason: "pm_failed", message: "stuck" })]);
    expect(s.status).toBe("escalated");
    s = applyEvent(s, ev("run_resumed", { guidance: "skip the flaky test" }));
    expect(s.status).toBe("running");
    expect(s.finished).toBeNull();
    expect(s.chat.at(-1)).toMatchObject({ kind: "user", text: "skip the flaky test" });
    expect(attention(s)).toBeNull(); // no longer stuck
  });

  it("global guardrail hits (no task) still appear in the conversation", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("guardrail_hit", { kind: "secret_scan", reason: "1 possible secret(s) found" }));
    expect(s.secretBlock?.kind).toBe("secret_scan");
    expect(s.chat.at(-1)).toMatchObject({ kind: "note", tone: "warn" });
  });

  it("still opens runs recorded before the Project Manager became a deep agent", () => {
    seq = 0;
    const s = replay([
      ev("run_started", { run_id: "r", project: "p", request: "x" }),
      ev("plan_ready", { reason: "Two steps.", tasks: [mk("a", "backend_developer", "pass"), mk("b", "qa_engineer", "pending")] }),
    ]);
    expect(s.todos.map((t) => t.status)).toEqual(["completed", "pending"]);
    expect(progress(s)).toEqual({ done: 1, total: 2 });
  });

  it("a plan item the Project Manager forgot to tick reads as done when that specialist's latest task passed", () => {
    seq = 0;
    const s = replay([
      ev("run_started", { run_id: "r", project: "p", request: "x" }),
      ev("todos_updated", { todos: [{ content: "Backend Developer: write it", status: "in_progress" }, { content: "QA Engineer: test it", status: "pending" }] }),
      ev("task_started", { task: mk("a", "backend_developer", "in_progress") }),
      ev("task_finished", { task: mk("a", "backend_developer", "pass"), verdict: "pass" }),
    ]);
    expect(s.todos.map((t) => todoUi(s, t))).toEqual(["passed", "queued"]); // running: only the in-progress item is inferred
    const done = applyEvent(applyEvent(s, ev("task_started", { task: mk("b", "qa_engineer", "in_progress") })), ev("task_finished", { task: mk("b", "qa_engineer", "pass"), verdict: "pass" }));
    const end = applyEvent(done, ev("run_finished", { status: "passed", reason: "all_passed", message: "ok" }));
    expect(end.todos.map((t) => todoUi(end, t))).toEqual(["passed", "passed"]); // a passed run never shows leftover Blocked items
  });

  it("shows when the Project Manager had to be asked to delegate", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("pm_nudged", { message: "x" }));
    expect(s.chat.at(-1)).toMatchObject({ kind: "note", tone: "warn" });
  });

  it("keeps the event log bounded", () => {
    seq = 0;
    let s = emptyRun();
    for (let i = 0; i < 900; i++) s = applyEvent(s, ev("tool_call", { task_id: "t", tool: "ls", summary: String(i) }));
    expect(s.log).toHaveLength(800);
  });

  it("formats durations", () => {
    expect([formatDuration(9), formatDuration(143), formatDuration(3600)]).toEqual(["9s", "2m 23s", "60m 00s"]);
  });
});
