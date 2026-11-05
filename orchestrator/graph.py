"""The orchestration graph: plan -> (approve) -> act -> (act | plan | escalate | report).

- `plan` asks the Project Manager role for a to-do list: a JSON list of tasks with `depends_on` and `writes`
  (on a replan, for the *remaining* work, with the failure evidence in the prompt). An invalid plan is sent back
  once; after that the run stops (`planner_failed`).
- `approve` (optional) shows the first plan and waits for a yes/no before any agent starts.
- `act` starts every *ready* task (its dependencies passed) up to `config.concurrency`, never two tasks whose write
  areas overlap. Each task runs one role agent (`run_role_traced`) with a write scope and a time limit, saves its
  reply as `runs/<run_id>/<task.id>.md` (and a per-attempt copy), and is observed *in code* right away:
  `parse_status` on the status block (never prose), then, for QA/DevOps, the real exit code of the sandbox tool.
- A failure sends the run back to `plan` (a replan); a task that fails its last attempt is `escalated` (terminal).
- `report` / `escalate` write `report.md`; `report` also scans for secrets and builds the zip.

Retry accounting: a task's `attempt` counts dispatches of that task. Replanning keeps a still-open task's `id` and
`attempt` when the new plan continues it: via `replaces` (any role), exactly (same role+objective), or, for the
task that just failed, as a revision of it (same role, reworded objective). So a planner cannot dodge the attempt
cap by rewording, and a role change on purpose keeps the count.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, NotRequired, TypedDict

from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace, git
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator.config import RunConfig
from orchestrator.delivery import build_zip
from orchestrator.events import EventLog
from orchestrator.guardrails import (
    ToolRecord,
    WriteScope,
    machine_verdict,
    writes_overlap,
)
from orchestrator.role_runner import (
    PlannedTask,
    RoleRun,
    parse_plan,
    plan_summary,
    run_role,
    run_role_traced,
)
from orchestrator.runs import run_dir, write_artifact
from orchestrator.sandbox_tools import sandbox_tools_for
from orchestrator.secrets import scan_secrets
from orchestrator.status_block import parse_status
from orchestrator.task import Task, TaskLog, save_task_log

_DEFAULTS = RunConfig()
MAX_ATTEMPTS = _DEFAULTS.max_attempts
MAX_TOTAL_DISPATCHES = _DEFAULTS.max_total_dispatches
PLANNER_ROLE = "project_manager"
TASK_LOG_FILE = "task_log.json"
OPEN_STATUSES = ("pending", "fail")
DEAD_STATUSES = ("escalated", "blocked", "superseded")

ROSTER = """\
- business_analyst: clarifies requirements and acceptance criteria
- product_manager: writes user stories and priorities
- solution_architect: designs the system and its interfaces
- code_analyst: reads and explains the existing code
- database_engineer: designs schemas and migrations
- backend_developer: implements server-side code
- frontend_developer: implements client-side code
- ui_ux_designer: designs screens and interactions
- qa_engineer: writes and runs tests (has a run_tests sandbox tool)
- devops_engineer: builds and packages the project (has a run_build sandbox tool)"""

STATUS_BLOCK_FORMAT = "---\nstatus: pass|fail\nreason: <one line>\n---"

PLAN_FORMAT = (
    "Reply with one or two sentences of reasoning, then a fenced ```json block holding a list of tasks, each\n"
    '{"key": "short-name", "role": ..., "objective": ..., "inputs": [...], "done_condition": ..., '
    '"depends_on": ["keys of tasks that must pass first"], "writes": ["folder/**"]}\n'
    'Tasks that can safely run at the same time must have different "writes" folders and no depends_on between '
    'them. Put QA after the code it tests. Leave "writes" empty only for a task that must run alone.'
)

REASONS = {
    "all_passed": "All tasks passed.",
    "task_escalated": "A task failed its last attempt.",
    "dispatch_cap": "The run hit its limit on dispatches.",
    "replan_cap": "The run hit its limit on replans.",
    "run_timeout": "The run hit its time limit.",
    "planner_failed": "The planner could not produce a valid plan.",
    "plan_rejected": "The plan was rejected.",
    "blocked_tasks": "Remaining tasks are blocked by tasks that did not pass.",
    "empty_plan": "The planner produced no tasks.",
}

Status = Literal["passed", "escalated", "stopped"]
ApproveFn = Callable[[dict[str, Any]], Awaitable[bool]]


class OrchestratorState(TypedDict):
    request: str
    workspace: Workspace
    run_id: str
    model: BaseChatModel
    sandbox_client: NotRequired[SandboxClient | None]
    task_log: TaskLog
    last_failure: str | None
    config: NotRequired[RunConfig]
    events: NotRequired[EventLog | None]
    approve: NotRequired[ApproveFn | None]
    start_at: NotRequired[Literal["plan", "act"]]
    base_commit: NotRequired[str | None]
    # Loop counters and outcome, set by the nodes.
    t0: NotRequired[float]
    total_dispatches: NotRequired[int]
    replans: NotRequired[int]
    end_reason: NotRequired[str | None]
    status: NotRequired[Status]
    approved: NotRequired[bool]


# ---------------------------------------------------------------- small helpers


def _cfg(state: OrchestratorState) -> RunConfig:
    return state.get("config") or _DEFAULTS


def _emit(state: OrchestratorState, type_: str, **data: Any) -> None:
    events = state.get("events")
    if events is not None:
        events.emit(type_, **data)


def _save(state: OrchestratorState, last_failure: str | None = None) -> None:
    log = state["task_log"]
    log.last_failure = last_failure
    save_task_log(log, run_dir(state["workspace"], state["run_id"]) / TASK_LOG_FILE)


def _payload(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "role": t.role,
        "objective": t.objective,
        "inputs": list(t.inputs),
        "done_condition": t.done_condition,
        "depends_on": list(t.depends_on),
        "writes": list(t.writes),
        "status": t.status,
        "attempt": t.attempt,
        "reason": t.reason,
    }


def _all_payloads(log: TaskLog) -> list[dict[str, Any]]:
    return [_payload(t) for t in log.tasks]


def _has_open_tasks(log: TaskLog) -> bool:
    return any(t.status in OPEN_STATUSES for t in log.tasks)


def _all_done(log: TaskLog) -> bool:
    return (
        bool(log.tasks)
        and all(t.status in ("pass", "superseded") for t in log.tasks)
        and any(t.status == "pass" for t in log.tasks)
    )


def _elapsed(state: OrchestratorState) -> float:
    return time.monotonic() - state["t0"] if "t0" in state else 0.0


def _summarize(record: ToolRecord, kind: str) -> str:
    if kind == "call":
        args = record.args
        if "file_path" in args:
            return str(args["file_path"])
        if "command" in args:
            return " ".join(map(str, args["command"]))[:120]
        return ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3])[:120]
    first = record.output.strip().splitlines()[0] if record.output.strip() else ""
    return first[:120]


# ---------------------------------------------------------------- planning


def _plan_prompt(state: OrchestratorState) -> str:
    log = state["task_log"]
    parts = [f"Request:\n{state['request']}", f"Roles you can assign tasks to:\n{ROSTER}"]
    done = [t for t in log.tasks if t.status == "pass"]
    if done:
        parts.append(
            "Already done (do not re-plan these):\n" + "\n".join(f"- [{t.id}] {t.role}: {t.objective}" for t in done)
        )
    open_tasks = [t for t in log.tasks if t.status in OPEN_STATUSES]
    if state["last_failure"]:
        if open_tasks:
            parts.append(
                "Still open (re-propose the ones you still want; keep the role and objective to keep them as they are):\n"
                + "\n".join(f"- [{t.id}] {t.role}: {t.objective} (tries so far: {t.attempt})" for t in open_tasks)
            )
        parts.append(
            f"The last task failed:\n{state['last_failure']}\n\n"
            "Give a revised plan for the REMAINING work only. To retry the failed task, keep its role "
            '(you may reword its objective), or set "replaces": "<its id>" to hand it to another role; either way '
            "it counts as that task's next attempt. A task gets at most 2 attempts in total."
        )
    elif open_tasks:
        parts.append("Open tasks from before:\n" + "\n".join(f"- [{t.id}] {t.role}: {t.objective}" for t in open_tasks))
    parts.append(PLAN_FORMAT)
    return "\n\n".join(parts)


def _check_refs(planned: list[PlannedTask], log: TaskLog) -> None:
    keys = {p.key for p in planned if p.key}
    existing = {t.id for t in log.tasks}
    for p in planned:
        for dep in p.depends_on:
            if dep not in keys and dep not in existing:
                raise ValueError(f"task {p.key or p.objective!r} depends on unknown task {dep!r}")


def _merge_plan(log: TaskLog, planned: list[PlannedTask]) -> list[Task]:
    """Closed tasks stay; the new plan replaces every open one. An open task the plan continues keeps its id and
    attempt count (`replaces`, then exact role+objective, then the failed task matching the first unclaimed planned
    task with its role). Open tasks the plan drops are kept in the log as `superseded`, never silently deleted."""
    closed = [t for t in log.tasks if t.status not in OPEN_STATUSES]
    open_tasks = [t for t in log.tasks if t.status in OPEN_STATUSES]
    claimed: dict[int, Task] = {}  # index in `planned` -> existing task it continues
    used: set[str] = set()

    for i, p in enumerate(planned):
        if p.replaces:
            match = next((t for t in open_tasks if t.id == p.replaces and t.id not in used), None)
            if match is not None:
                claimed[i] = match
                used.add(match.id)
    for i, p in enumerate(planned):
        if i in claimed:
            continue
        for t in open_tasks:
            if t.id not in used and t.role == p.role and t.objective == p.objective:
                claimed[i] = t
                used.add(t.id)
                break
    for t in open_tasks:
        if t.status != "fail" or t.id in used:
            continue
        for i, p in enumerate(planned):
            if i not in claimed and p.role == t.role:
                claimed[i] = t
                used.add(t.id)
                break

    merged: list[Task] = []
    key_to_id: dict[str, str] = {}
    for i, p in enumerate(planned):
        task = claimed.get(i)
        if task is None:
            task = Task(
                id=uuid.uuid4().hex[:8], role=p.role, objective=p.objective, inputs=(), done_condition="", status="pending"
            )
        task.role = p.role
        task.objective = p.objective
        task.inputs = tuple(p.inputs)
        task.done_condition = p.done_condition
        task.writes = tuple(p.writes)
        merged.append(task)
        if p.key:
            key_to_id[p.key] = task.id
    for task, p in zip(merged, planned, strict=True):
        task.depends_on = tuple(key_to_id.get(d, d) for d in p.depends_on)

    superseded = [t for t in open_tasks if t.id not in used]
    for t in superseded:
        t.status = "superseded"
        t.reason = "dropped by the replan"
    return closed + superseded + merged


def _settle_blocked(state: OrchestratorState) -> None:
    """A pending task whose dependency can never pass (escalated, blocked, dropped, unknown) is blocked."""
    log = state["task_log"]
    changed = True
    while changed:
        changed = False
        by_id = {t.id: t for t in log.tasks}
        for t in log.tasks:
            if t.status not in OPEN_STATUSES:
                continue
            for dep in t.depends_on:
                d = by_id.get(dep)
                if d is None or d.status in DEAD_STATUSES:
                    t.status = "blocked"
                    t.reason = f"depends on {dep}, which is {d.status if d else 'unknown'}"
                    _emit(state, "task_blocked", task=t.id, reason=t.reason)
                    changed = True
                    break


async def plan_node(state: OrchestratorState) -> dict[str, Any]:
    cfg, log = _cfg(state), state["task_log"]
    t0 = state.get("t0", time.monotonic())
    is_replan = bool(state["last_failure"])
    replans = state.get("replans", 0)
    base: dict[str, Any] = {"t0": t0}
    if time.monotonic() - t0 > cfg.run_timeout_s:
        return {**base, "end_reason": "run_timeout", "last_failure": state["last_failure"]}
    if is_replan:
        if replans >= cfg.max_replans:
            return {**base, "end_reason": "replan_cap", "last_failure": state["last_failure"]}
        replans += 1
    _emit(state, "replan_started" if is_replan else "plan_started", replans=replans)

    planned: list[PlannedTask] | None = None
    reply, error = "", ""
    for attempt in range(cfg.max_plan_attempts):
        prompt = _plan_prompt(state)
        if error:
            prompt += f"\n\nYour previous reply was rejected: {error}\nFix it and reply again."
        reply = await run_role(PLANNER_ROLE, prompt, state["model"], state["workspace"].work, extra_tools=())
        try:
            planned = parse_plan(reply)
            _check_refs(planned, log)
            break
        except ValueError as exc:
            planned, error = None, str(exc)[:300]
            _emit(state, "plan_invalid", error=error, attempt=attempt + 1)
    if planned is None:
        failure = state["last_failure"] or error
        _save(state, failure)
        return {**base, "end_reason": "planner_failed", "last_failure": failure, "replans": replans}

    if any(p.role == PLANNER_ROLE for p in planned):
        _emit(
            state,
            "plan_warning",
            message="Tasks assigned to the Project Manager were dropped: it plans, it does not run tasks.",
        )
    planned = [p for p in planned if p.role != PLANNER_ROLE]
    failed = [t for t in log.tasks if t.status == "fail"]
    log.tasks = _merge_plan(log, planned)
    last_failure: str | None = None
    end_reason: str | None = None
    if not _has_open_tasks(log):
        if state["last_failure"]:
            # The planner gave up on the failing task without re-proposing it: record it as escalated and keep
            # `last_failure` so the run goes to escalate.
            for t in failed:
                if t.status == "superseded":
                    t.status = "escalated"
                    t.reason = "the planner dropped it after a failure"
            last_failure = state["last_failure"]
        elif not log.tasks:
            end_reason = "empty_plan"
    _save(state, last_failure)
    _emit(state, "plan_ready", replan=is_replan, reason=plan_summary(reply), tasks=_all_payloads(log))
    return {**base, "task_log": log, "last_failure": last_failure, "replans": replans, "end_reason": end_reason}


def _needs_approval(state: OrchestratorState) -> bool:
    return (
        _cfg(state).plan_approval
        and state.get("approve") is not None
        and not state.get("approved")
        and not any(t.attempt > 0 for t in state["task_log"].tasks)
    )


def route_after_plan(state: OrchestratorState) -> Literal["approve", "act", "escalate"]:
    if state.get("end_reason"):
        return "escalate"
    if _has_open_tasks(state["task_log"]):
        return "approve" if _needs_approval(state) else "act"
    return "escalate"


async def approve_node(state: OrchestratorState) -> dict[str, Any]:
    approve = state.get("approve")
    assert approve is not None  # _needs_approval checked
    _emit(state, "plan_approval_requested", tasks=_all_payloads(state["task_log"]))
    ok = await approve({"tasks": _all_payloads(state["task_log"])})
    _emit(state, "plan_approved" if ok else "plan_rejected")
    return {"approved": True} if ok else {"approved": False, "end_reason": "plan_rejected"}


def route_after_approve(state: OrchestratorState) -> Literal["act", "escalate"]:
    return "escalate" if state.get("end_reason") else "act"


# ---------------------------------------------------------------- acting + observing


def _ready(log: TaskLog) -> list[Task]:
    passed = {t.id for t in log.tasks if t.status == "pass"}
    return [t for t in log.tasks if t.status in OPEN_STATUSES and all(d in passed for d in t.depends_on)]


def _select_batch(ready: list[Task], slots: int) -> list[Task]:
    batch: list[Task] = []
    for t in ready:
        if len(batch) >= slots:
            break
        if all(not writes_overlap(t.writes, b.writes) for b in batch):
            batch.append(t)
    return batch


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _commit(state: OrchestratorState, task: Task) -> None:
    ws = state["workspace"]
    if not (ws.work / ".git").exists():
        return
    try:
        ws.commit_all(f"{task.role}: {task.objective[:60]} [{task.id}]")
    except RuntimeError as exc:
        _emit(state, "plan_warning", message=f"could not commit {task.id}: {exc}"[:200])


async def _run_task(state: OrchestratorState, task: Task, dispatches_after: int, failures: list[str]) -> None:
    cfg, ws = _cfg(state), state["workspace"]
    task.status = "in_progress"
    task.attempt += 1
    _save(state, state["last_failure"])
    _emit(state, "task_started", task=_payload(task))

    objective_text = (
        f"{task.objective}\n\n"
        f"Inputs: {', '.join(task.inputs) or 'none'}\n"
        f"Done when: {task.done_condition}\n\n"
        f"Your reply is saved as the result artifact `{task.id}.md`. End it with exactly this status block "
        f"(status is pass only if the done condition is met):\n{STATUS_BLOCK_FORMAT}"
    )
    client = state.get("sandbox_client")
    tools = sandbox_tools_for(task.role, client, ws.path.name) if client is not None else []

    def on_tool(kind: str, record: ToolRecord) -> None:
        _emit(
            state,
            "tool_call" if kind == "call" else "tool_result",
            task=task.id,
            role=task.role,
            tool=record.name,
            summary=_summarize(record, kind),
            error=record.error,
        )

    def on_block(tool: str, path: str, reason: str) -> None:
        _emit(
            state, "guardrail_hit", kind="write_blocked", task=task.id, role=task.role, tool=tool, path=path, reason=reason
        )

    scope = WriteScope(task.writes, cfg.max_file_bytes, cfg.max_files_per_task)
    run = RoleRun("")
    error = ""
    try:
        run = await asyncio.wait_for(
            run_role_traced(
                task.role,
                objective_text,
                state["model"],
                ws.work,
                tools,
                write_scope=scope,
                on_block=on_block,
                on_tool=on_tool,
            ),
            cfg.task_timeout_s,
        )
    except TimeoutError:
        error = f"timed out after {cfg.task_timeout_s:g}s"
        _emit(state, "guardrail_hit", kind="task_timeout", task=task.id, role=task.role, reason=error)
    except Exception as exc:  # noqa: BLE001 (any agent/model/sandbox failure is a failed attempt, not a crashed run)
        error = f"{type(exc).__name__}: {exc}"[:300]

    artifact = run.text or f"(no result: {error or 'the agent replied with nothing'})"
    write_artifact(ws, state["run_id"], f"{task.id}.attempt{task.attempt}.md", artifact)
    write_artifact(ws, state["run_id"], f"{task.id}.md", artifact)

    # Observe: in code, never trusting prose.
    result = parse_status(artifact)
    status, reason = result.status, result.reason
    if error:
        status, reason = "fail", error
    elif tools and (verdict := machine_verdict(task.role, run.calls)) is not None:
        ok, why = verdict
        if not ok and status == "pass":
            _emit(state, "guardrail_hit", kind="status_overridden", task=task.id, role=task.role, reason=why)
            status, reason = "fail", why
        elif not ok:
            reason = f"{reason}; {why}"

    repeated = bool(task.reasons) and _norm(task.reasons[-1]) == _norm(reason)
    will_retry = False
    task.reason = reason
    if status == "pass":
        task.status = "pass"
        _commit(state, task)
    else:
        task.reasons.append(reason)
        if task.attempt >= cfg.max_attempts or dispatches_after >= cfg.max_total_dispatches or repeated:
            task.status = "escalated"
        else:
            task.status = "fail"
            will_retry = True
            failures.append(
                f"role: {task.role}\nobjective: {task.objective}\ndone_condition: {task.done_condition}\n"
                f"attempt: {task.attempt}\nreason: {reason}\n"
                f"artifact (last {cfg.max_failure_chars} chars):\n{artifact[-cfg.max_failure_chars :]}"
            )
    _save(state, state["last_failure"])
    _emit(
        state,
        "task_finished",
        task=_payload(task),
        verdict=status,
        will_retry=will_retry,
        artifact=f"{task.id}.md",
        tool_calls=len(run.calls),
    )


async def act_node(state: OrchestratorState) -> dict[str, Any]:
    cfg, log = _cfg(state), state["task_log"]
    t0 = state.get("t0", time.monotonic())
    base: dict[str, Any] = {"t0": t0}
    if time.monotonic() - t0 > cfg.run_timeout_s:
        return {**base, "end_reason": "run_timeout"}
    _settle_blocked(state)
    dispatched = state.get("total_dispatches", 0)
    slots = min(cfg.concurrency, cfg.max_total_dispatches - dispatched)
    ready = _ready(log)
    batch = _select_batch(ready, slots)
    if not batch:
        _save(state, state["last_failure"])
        reason = "dispatch_cap" if ready and slots <= 0 else "blocked_tasks"
        return {**base, "task_log": log, "end_reason": reason}
    failures: list[str] = []
    after = dispatched + len(batch)
    await asyncio.gather(*(_run_task(state, t, after, failures) for t in batch))
    return {**base, "task_log": log, "total_dispatches": after, "last_failure": "\n\n".join(failures) or None}


def route_after_act(state: OrchestratorState) -> Literal["act", "plan", "escalate", "report"]:
    log = state["task_log"]
    if state.get("end_reason") or any(t.status == "escalated" for t in log.tasks):
        return "escalate"
    if any(t.status == "fail" for t in log.tasks):
        return "plan"
    if _has_open_tasks(log):
        return "act"
    return "report" if _all_done(log) else "escalate"


# ---------------------------------------------------------------- finishing


def _outcome(state: OrchestratorState) -> tuple[Status, str]:
    reason = state.get("end_reason")
    if reason is None:
        log = state["task_log"]
        reason = "task_escalated" if any(t.status == "escalated" for t in log.tasks) else "blocked_tasks"
    return ("stopped" if reason == "plan_rejected" else "escalated"), reason


def _report_markdown(state: OrchestratorState, status: Status, reason: str, delivery: str, summary: str) -> str:
    log, cfg = state["task_log"], _cfg(state)
    reason_text = REASONS.get(reason, reason)
    if reason == "dispatch_cap":
        reason_text += f" ({cfg.max_total_dispatches})"
    lines = [
        f"# Run {state['run_id']}: {status}",
        "",
        f"**Request:** {state['request']}",
        "",
        f"**Result:** {reason_text}",
        "",
    ]
    if summary:
        lines += ["## Summary", "", summary.strip(), ""]
    lines += ["## Tasks", "", "| Role | Objective | Result | Tries | Reason |", "|---|---|---|---|---|"]
    for t in log.tasks:
        lines.append(
            f"| {t.role} | {t.objective.replace('|', '/')} | {t.status} | {t.attempt} | {t.reason.replace('|', '/')} |"
        )
    failing = [t for t in log.tasks if t.status in ("escalated", "fail", "blocked")]
    if failing:
        lines += ["", "## What did not pass", ""]
        lines += [f"- **{t.role}** ({t.id}): {t.reason or t.status}. Evidence: `{t.id}.md`." for t in failing]
    base = state.get("base_commit")
    ws = state["workspace"]
    stat = git(ws.work, "diff", "--stat", f"{base}..HEAD", check=False) if base and (ws.work / ".git").exists() else ""
    lines += ["", "## Files changed", "", "```", stat or "(no committed changes)", "```"]
    events = state.get("events")
    hits = [e for e in (events.since(0) if events else []) if e["type"] == "guardrail_hit"]
    if hits:
        lines += ["", "## Guardrails that fired", ""]
        lines += [f"- {h['kind']}: {h.get('reason', '')} {h.get('path', '')}".rstrip() for h in hits]
    lines += ["", "## Delivery", "", delivery, ""]
    return "\n".join(lines)


async def _write_report(state: OrchestratorState, status: Status, reason: str, delivery: str) -> None:
    summary = ""
    if _cfg(state).report_summary:
        digest = "\n".join(f"- {t.role}: {t.objective} -> {t.status}" for t in state["task_log"].tasks)
        try:
            summary = await run_role(
                PLANNER_ROLE,
                "Write a three-sentence summary of this finished run for the person who asked.\n"
                f"Request: {state['request']}\nOutcome: {status}\nTasks:\n{digest}",
                state["model"],
                state["workspace"].work,
            )
        except Exception:  # noqa: BLE001 (the summary is optional; the table below is the report)
            summary = ""
    markdown = _report_markdown(state, status, reason, delivery, summary)
    write_artifact(state["workspace"], state["run_id"], "report.md", markdown)
    _emit(state, "report_ready", path="report.md")


def _finish(state: OrchestratorState, status: Status, reason: str) -> None:
    counts: dict[str, int] = {}
    for t in state["task_log"].tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    _save(state, state["last_failure"])
    _emit(
        state,
        "run_finished",
        status=status,
        reason=reason,
        message=REASONS.get(reason, reason),
        tasks=counts,
        dispatches=state.get("total_dispatches", 0),
        seconds=round(_elapsed(state), 1),
    )


async def report_node(state: OrchestratorState) -> dict[str, Any]:
    """All tasks passed: scan for secrets, write the report, build the zip."""
    ws, run_id = state["workspace"], state["run_id"]
    findings = scan_secrets(ws.work)
    if findings:
        shown = [{"path": f.path, "line": f.line, "kind": f.kind} for f in findings[:20]]
        _emit(
            state, "guardrail_hit", kind="secret_scan", reason=f"{len(findings)} possible secret(s) found", findings=shown
        )
        delivery = "The zip was **not built**: the secret scan found possible secrets:\n\n" + "\n".join(
            f"- `{f.path}` line {f.line}: {f.kind}" for f in findings[:20]
        )
    else:
        delivery = (
            "`delivery.zip` (project files at the root, this report and the artifacts under `docs/orchestrator/`)."
        )
    await _write_report(state, "passed", "all_passed", delivery)
    if not findings:
        dest = run_dir(ws, run_id) / "delivery.zip"
        _, count = build_zip(ws.work, run_dir(ws, run_id), dest)
        _emit(state, "delivery_ready", path="delivery.zip", files=count, partial=False)
    _finish(state, "passed", "all_passed")
    return {"status": "passed", "end_reason": "all_passed"}


async def escalate_node(state: OrchestratorState) -> dict[str, Any]:
    """Terminal: a task failed its last attempt, the planner gave up, or a run limit was hit. Writes the report
    (what passed, what failed, the evidence); a partial zip is offered only when asked for."""
    _settle_blocked(state)  # tasks waiting on something that can no longer pass are blocked, not left pending
    status, reason = _outcome(state)
    await _write_report(
        state, status, reason, "No zip was built because the run did not finish. A partial zip can be requested."
    )
    _finish(state, status, reason)
    return {"status": status, "end_reason": reason}


def route_start(state: OrchestratorState) -> Literal["plan", "act"]:
    return state.get("start_at", "plan")


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", plan_node)
    graph.add_node("approve", approve_node)
    graph.add_node("act", act_node)
    graph.add_node("report", report_node)
    graph.add_node("escalate", escalate_node)
    graph.set_conditional_entry_point(route_start, {"plan": "plan", "act": "act"})
    graph.add_conditional_edges("plan", route_after_plan, {"approve": "approve", "act": "act", "escalate": "escalate"})
    graph.add_conditional_edges("approve", route_after_approve, {"act": "act", "escalate": "escalate"})
    graph.add_conditional_edges(
        "act", route_after_act, {"act": "act", "plan": "plan", "escalate": "escalate", "report": "report"}
    )
    graph.add_edge("report", END)
    graph.add_edge("escalate", END)
    return graph.compile()
