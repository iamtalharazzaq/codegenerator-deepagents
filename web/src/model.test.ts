import { describe, expect, it } from "vitest";

import { mockEvents, mockRuns, mockSource, mockView } from "./mock";
import {
  agentUi, applyEvent, allGuardrails, attention, fileTree, groupOf, headline, isWorking, levelOf, RUN_LABEL, relativeTime, retries, runFiles, segments, swimlane, timeline, emptyRun, feed, formatDuration, nowLine, progress, repeatsEarlier, replay, roleOfTodo, runTitle, runUi, taskUi, todoUi, waves, type RunEvent,
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
    expect(withText).toHaveLength(3); // three replans: the architect once, the backend twice
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
    expect(view.pmNotes).toHaveLength(4);
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
    expect(view.finished?.summary).toContain("12 tests are green");
    expect(view.zip).toEqual({ files: 7, partial: false });
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

  it("the final review: waits for the person, and a change request becomes a message in the feed", () => {
    const s = mockView("review");
    expect(s.status).toBe("running");
    expect(s.review).toMatchObject({ round: 1, files: expect.arrayContaining(["calculator.js", "index.html", "docs/architecture.md"]) });
    expect(s.zip).toBeNull(); // nothing is delivered before the person decides
    expect(nowLine(s)).toEqual({ ui: "blocked", text: "Waiting for your review before the zip is built" });
    seq = s.lastSeq;
    const asked = applyEvent(s, ev("review_changes_requested", { round: 1, text: "also add a README" }));
    expect(asked.review).toBeNull();
    expect(feed(asked).at(-1)).toMatchObject({ kind: "user", text: "also add a README" });
    const second = applyEvent(asked, ev("review_requested", { round: 2, summary: "Added a README.", files: ["README.md"] }));
    expect(second.review?.round).toBe(2);
    const accepted = applyEvent(second, ev("review_accepted", { round: 2 }));
    expect(accepted.review).toBeNull();
    expect(applyEvent(second, ev("run_finished", { status: "passed", reason: "all_passed", message: "ok" })).review).toBeNull();
  });

  it("shows when the Project Manager had to be asked to delegate", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("pm_nudged", { message: "x" }));
    expect(s.chat.at(-1)).toMatchObject({ kind: "note", tone: "warn" });
  });

  it("shows a plan that changed after work started", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("plan_revised", { added: ["QA Engineer: retest"], message: "The Project Manager changed the plan after work started: QA Engineer: retest" }));
    expect(String((s.chat.at(-1) as { text: string }).text)).toContain("changed the plan");
  });

  it("shows when failed work was sent back to the Project Manager for a retry", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("retry_requested", { round: 1, message: "- task ab (QA Engineer, try 1 of 3): tests failed" }));
    expect(s.chat.at(-1)).toMatchObject({ kind: "note", tone: "warn" });
    expect(String((s.chat.at(-1) as { text: string }).text)).toContain("tests failed");
    expect(s.pm).toBe("planning");
  });

  it("a run waiting for the person is Needs approval, not Running", () => {
    seq = 0;
    let s = applyEvent(emptyRun(), ev("run_started", { run_id: "r", project: "p", request: "x" }));
    expect([headline(s).label, isWorking(s)]).toEqual(["Running", true]);
    s = applyEvent(s, ev("plan_approval_requested", { todos: [{ content: "Backend Developer: a", status: "pending" }] }));
    expect([headline(s).label, headline(s).ui, isWorking(s)]).toEqual(["Needs approval", "blocked", false]);
    s = applyEvent(s, ev("plan_approved", {}));
    expect([headline(s).label, isWorking(s)]).toEqual(["Running", true]);
    s = applyEvent(s, ev("review_requested", { round: 1, summary: "done", files: [] }));
    expect([headline(s).label, isWorking(s)]).toEqual(["Needs approval", false]);
    expect([runUi("needs_approval"), RUN_LABEL.needs_approval]).toEqual(["blocked", "Needs approval"]);
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

describe("the passed example (make a calculator)", () => {
  const view = mockView("passed");

  it("is 3 of 3 tasks in 43 seconds with 7 files and a markdown result", () => {
    expect(view.request).toBe("make a calculator");
    expect(progress(view)).toEqual({ done: 3, total: 3 });
    expect([view.dispatches, view.maxDispatches]).toEqual([3, 20]);
    expect(view.endedAt! - view.startedAt).toBe(43);
    expect(view.zip).toEqual({ files: 7, partial: false });
    expect(runFiles(view)).toHaveLength(7);
    expect(view.finished?.summary).toMatch(/^## Summary/);
    expect(headline(view)).toEqual({ ui: "passed", label: "Passed" });
    expect(retries(view)).toBe(0);
  });

  it("has one passed segment per task", () => {
    expect(segments(view)).toEqual(["passed", "passed", "passed"]);
  });
});

describe("selectors for the redesigned screen", () => {
  const view = mockView("escalated");

  it("collects the files agents wrote, and leaves out the write that a guardrail blocked", () => {
    expect(runFiles(view)).toEqual(expect.arrayContaining(["docs/requirements.md", "architecture_design.md", "backend/server.js"]));
    expect(runFiles(view)).not.toContain("calculator_app_architecture.md");
    expect(runFiles(view)).not.toContain("/server.js");
  });

  it("builds a folder tree with folders first", () => {
    const tree = fileTree(["z.md", "backend/a.js", "backend/lib/b.js", "a.md"]);
    expect(tree.map((n) => n.name)).toEqual(["backend", "a.md", "z.md"]);
    expect(tree[0].children.map((n) => n.name)).toEqual(["lib", "a.js"]);
  });

  it("gathers every guardrail hit of the run for the Attention card", () => {
    expect(allGuardrails(view).map((g) => g.kind)).toEqual(["write_blocked", "write_blocked", "write_blocked"]);
    expect(allGuardrails(view).map((g) => g.seq)).toEqual([...allGuardrails(view).map((g) => g.seq)].sort((a, b) => a - b));
  });

  it("counts retries (repeat tries) for the stats row", () => {
    expect(retries(view)).toBe(2);
  });

  it("shows the Project Manager's reasoning in the timeline, in order, marking later notes as replans", () => {
    const pm = timeline(view).filter((i) => i.kind === "pm");
    expect(pm).toHaveLength(4);
    expect(pm.map((p) => p.kind === "pm" && p.replan)).toEqual([false, true, true, true]);
    expect(timeline(view).map((i) => i.seq)).toEqual([...timeline(view).map((i) => i.seq)].sort((a, b) => a - b));
  });

  it("lays the swimlane out as stages, with the specialists that never started waiting on the one that failed", () => {
    const lanes = swimlane(view);
    expect(lanes.slice(0, 6).map((l) => l.nodes.map((n) => `${n.role}#${n.tries}`))).toEqual([
      ["business_analyst#1"], ["product_manager#1"], ["solution_architect#1"], ["solution_architect#2"], ["backend_developer#1"], ["backend_developer#2"],
    ]);
    const last = lanes[lanes.length - 1];
    expect(last.label).toContain("not started");
    expect(last.nodes.map((n) => n.role)).toEqual(expect.arrayContaining(["frontend_developer", "qa_engineer", "devops_engineer"]));
    expect(last.nodes.every((n) => n.blockedBy === "backend_developer" && n.ui === "blocked")).toBe(true);
  });

  it("classifies log entries into levels", () => {
    const levels = new Set(view.log.map(levelOf));
    expect(levels).toEqual(new Set(["info", "warn", "error"]));
  });

  it("groups runs into Today, Yesterday and Earlier by calendar day, and prints a short relative time", () => {
    const noon = new Date(2026, 10, 6, 12, 0, 0).getTime() / 1000;
    expect(groupOf(noon - 3600, noon)).toBe("Today");
    expect(groupOf(noon - 86_400, noon)).toBe("Yesterday");
    expect(groupOf(noon - 5 * 86_400, noon)).toBe("Earlier");
    expect(relativeTime(noon - 20, noon)).toBe("just now");
    expect(relativeTime(noon - 600, noon)).toBe("10m ago");
    expect(relativeTime(noon - 7200, noon)).toBe("2h ago");
    expect(relativeTime(noon - 3 * 86_400, noon)).toBe("3d ago");
  });

  it("the mock runs list covers all three groups, including a long repeated title", () => {
    const rows = mockRuns();
    expect(new Set(rows.map((r) => groupOf(r.created_at)))).toEqual(new Set(["Today", "Yesterday", "Earlier"]));
    expect(rows.filter((r) => r.request.length > 100).length).toBeGreaterThanOrEqual(2);
  });

  it("serves reports, task results and file previews for the mock runs", async () => {
    const source = mockSource("passed");
    expect(await source.report("a50a01c8")).toContain("make a calculator");
    expect(await source.file("a50a01c8", "calculator.js")).toContain("evaluate");
    await expect(source.file("a50a01c8", "nope.txt")).rejects.toThrow();
    const task = mockView("passed").tasks[0];
    expect(await source.artifact("a50a01c8", `${task.id}.attempt1.md`)).toContain("solution architect");
  });
});

describe("the plan can be sent back with changes", () => {
  it("returns to planning, records the note, and waits for the revised plan again", () => {
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_started")]);
    s = applyEvent(s, ev("plan_approval_requested", { todos: [{ content: "Backend Developer: build", status: "pending" }] }));
    s = applyEvent(s, ev("plan_changes_requested", { text: "also add tests" }));
    expect(s.awaitingApproval).toBe(false);
    expect(s.pm).toBe("planning");
    expect(s.chat.at(-1)).toMatchObject({ kind: "user", text: "Changes to the plan: also add tests" });
    s = applyEvent(s, ev("todos_updated", { todos: [{ content: "Backend Developer: build", status: "pending" }, { content: "QA Engineer: tests", status: "pending" }] }));
    s = applyEvent(s, ev("plan_approval_requested", { todos: s.todos }));
    expect(s.awaitingApproval).toBe(true);
    expect(s.todos).toHaveLength(2);
    expect(s.todoChanges.length).toBeGreaterThan(0); // the revision shows in the plan history
  });
});

describe("run titles", () => {
  it("make a short heading from the prompt", () => {
    expect(runTitle("Make a calculator")).toBe("Make a calculator");
    expect(runTitle("  Please   create a calculator in python.  It should be tested. ")).toBe("Create a calculator in python");
    expect(runTitle("I want you to build a wishlist feature for the shop")).toBe("Build a wishlist feature for the shop");
    expect(runTitle("can you, please, add a forgot-password flow?")).toBe("Add a forgot-password flow");
    expect(runTitle("")).toBe("Untitled run");
    expect(runTitle("", "a50a01c8")).toBe("a50a01c8");
  });

  it("cut a long prompt at a word boundary", () => {
    const title = runTitle("Build a complete online bookstore with a catalogue, a shopping cart, user accounts, payments and an admin dashboard");
    expect(title.length).toBeLessThanOrEqual(57);
    expect(title.endsWith("…")).toBe(true);
    expect(runTitle("Create a forgot-password flow for the shop with an email link and expiry")).toBe("Create a forgot-password flow for the shop with an…".replace(" with an", ""));
    expect(title).toBe("Build a complete online bookstore with a catalogue…");
  });
});

describe("changes asked after the work", () => {
  it("plans again and asks for approval of the new plan before anything runs", () => {
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_started")]);
    s = applyEvent(s, ev("review_requested", { round: 1, summary: "done", files: ["a.py"] }));
    s = applyEvent(s, ev("review_changes_requested", { round: 1, text: "remove the html file" }));
    expect(s.review).toBeNull();
    expect(s.pm).toBe("planning");
    expect(s.chat.at(-1)).toMatchObject({ kind: "user", text: "remove the html file" });
    s = applyEvent(s, ev("plan_reopened"));
    s = applyEvent(s, ev("todos_updated", { todos: [{ content: "Frontend Developer: delete ui.html", status: "pending" }] }));
    s = applyEvent(s, ev("plan_approval_requested", { todos: s.todos }));
    expect(s.awaitingApproval).toBe(true);
    expect(s.todos.map((t) => t.content)).toEqual(["Frontend Developer: delete ui.html"]);
  });
});
