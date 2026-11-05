import { describe, expect, it } from "vitest";

import { applyEvent, emptyRun, nodeState, replay, stages, type RunEvent, type TaskView } from "./model";

const task = (id: string, role: string, extra: Partial<TaskView> = {}): TaskView => ({
  id, role, objective: `do ${id}`, inputs: [], done_condition: "ok", depends_on: [], writes: [], status: "pending", attempt: 0, reason: "", ...extra,
});
let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}): RunEvent => ({ seq: ++seq, ts: 0, type, ...data });

describe("reducer", () => {
  it("shows the plan, who is working, and the verdict ring", () => {
    seq = 0;
    const a = task("a", "code_analyst"), b = task("b", "backend_developer", { depends_on: ["a"] });
    let s = replay([
      ev("run_started", { run_id: "r1", project: "demo", request: "add reset", concurrency: 2 }),
      ev("plan_started"),
    ]);
    expect(s.pm).toBe("planning");
    s = applyEvent(s, ev("plan_ready", { reason: "Two steps.", tasks: [a, b] }));
    expect(s.pm).toBe("idle");
    expect(s.chat.map((c) => c.kind)).toEqual(["user", "pm"]);
    s = applyEvent(s, ev("task_started", { task: { ...a, status: "in_progress", attempt: 1 } }));
    expect(s.pm).toBe("waiting");
    expect(nodeState(s.tasks, "code_analyst")).toEqual({ cls: "active", word: "working · try 1" });
    expect(s.pulses.at(-1)).toMatchObject({ role: "code_analyst", back: false });
    s = applyEvent(s, ev("tool_call", { task_id: "a", tool: "write_file", summary: "/docs/map.md" }));
    expect(s.toolLines.a).toEqual(["write_file /docs/map.md"]);
    s = applyEvent(s, ev("task_finished", { task: { ...a, status: "pass", attempt: 1, reason: "mapped" }, verdict: "pass", will_retry: false }));
    expect(s.check).toBe("pass");
    expect(s.pm).toBe("checking");
    expect(nodeState(s.tasks, "code_analyst").cls).toBe("pass");
    expect(s.pulses.at(-1)).toMatchObject({ back: true });
  });

  it("keeps the delegated state while another task is still running", () => {
    seq = 0;
    const a = task("a", "database_engineer"), b = task("b", "backend_developer");
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_ready", { tasks: [a, b] })]);
    s = applyEvent(s, ev("task_started", { task: { ...a, status: "in_progress", attempt: 1 } }));
    s = applyEvent(s, ev("task_started", { task: { ...b, status: "in_progress", attempt: 1 } }));
    s = applyEvent(s, ev("task_finished", { task: { ...a, status: "pass", attempt: 1 }, verdict: "pass", will_retry: false }));
    expect(s.pm).toBe("waiting"); // b is still working
    expect(nodeState(s.tasks, "backend_developer").cls).toBe("active");
    expect(s.dispatches).toBe(2);
  });

  it("records a replan as added and removed work, and marks a last-attempt failure as final", () => {
    seq = 0;
    const q = task("q", "qa_engineer");
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_ready", { tasks: [q] })]);
    s = applyEvent(s, ev("task_finished", { task: { ...q, status: "fail", attempt: 1, reason: "red" }, verdict: "fail", will_retry: true }));
    expect(s.chat.at(-1)).toMatchObject({ kind: "result", ok: false, final: false });
    const fix = task("f", "backend_developer");
    s = applyEvent(s, ev("replan_started", { replans: 1 }));
    expect(s.pm).toBe("replanning");
    s = applyEvent(s, ev("plan_ready", { replan: true, reason: "Add a fix.", tasks: [{ ...q, status: "pending", attempt: 1 }, fix] }));
    expect(s.plans.at(-1)).toMatchObject({ replan: true, added: ["do f"], removed: [] });
    s = applyEvent(s, ev("task_finished", { task: { ...q, status: "escalated", attempt: 2 }, verdict: "fail", will_retry: false }));
    expect(s.chat.at(-1)).toMatchObject({ final: true });
  });

  it("handles approval, guardrails, delivery and the end of a run", () => {
    seq = 0;
    const a = task("a", "code_analyst");
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("plan_approval_requested", { tasks: [a] })]);
    expect(s.awaitingApproval && s.pm === "approval").toBe(true);
    s = applyEvent(s, ev("plan_approved"));
    expect(s.awaitingApproval).toBe(false);
    s = applyEvent(s, ev("guardrail_hit", { kind: "write_blocked", path: "/x", reason: "outside this task's write scope", role: "backend_developer" }));
    expect(s.guardrails).toHaveLength(1);
    s = applyEvent(s, ev("delivery_ready", { files: 7, partial: false }));
    s = applyEvent(s, ev("run_finished", { status: "passed", reason: "all_passed", message: "All tasks passed." }));
    expect(s.status).toBe("passed");
    expect(s.zip).toEqual({ files: 7, partial: false });
    expect(s.pm).toBe("done");
    expect(s.chat.at(-1)).toMatchObject({ kind: "done" });
  });

  it("flags a blocked zip from the secret scan", () => {
    seq = 0;
    const s = applyEvent(emptyRun(), ev("guardrail_hit", { kind: "secret_scan", reason: "1 possible secret(s) found" }));
    expect(s.secretBlock?.kind).toBe("secret_scan");
  });

  it("a resumed run continues in the same state with the guidance in the chat", () => {
    seq = 0;
    let s = replay([ev("run_started", { run_id: "r", project: "p", request: "x" }), ev("run_finished", { status: "escalated", reason: "task_escalated", message: "A task failed its last attempt." })]);
    expect(s.status).toBe("escalated");
    s = applyEvent(s, ev("run_resumed", { guidance: "skip the flaky test" }));
    expect(s.status).toBe("running");
    expect(s.chat.at(-1)).toMatchObject({ kind: "user", text: "skip the flaky test" });
  });
});

describe("stages", () => {
  it("groups tasks that can run together and hides superseded ones", () => {
    const tasks = [
      task("m", "code_analyst"),
      task("d", "solution_architect", { depends_on: ["m"] }),
      task("db", "database_engineer", { depends_on: ["d"] }),
      task("api", "backend_developer", { depends_on: ["d"] }),
      task("old", "qa_engineer", { status: "superseded" }),
      task("qa", "qa_engineer", { depends_on: ["db", "api"] }),
    ];
    const s = stages(tasks);
    expect(s.map((x) => x.tasks.map((t) => t.id))).toEqual([["m"], ["d"], ["db", "api"], ["qa"]]);
  });

  it("does not loop on a cycle", () => {
    const s = stages([task("a", "code_analyst", { depends_on: ["b"] }), task("b", "code_analyst", { depends_on: ["a"] })]);
    expect(s.flatMap((x) => x.tasks)).toHaveLength(2);
  });
});
