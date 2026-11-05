"""The team: a Project Manager deep agent that delegates to the specialists as deepagents sub-agents.

The Project Manager is one `create_deep_agent(...)`. Its ten specialists are declared with `subagents=[...]`, so it
reaches them with deepagents' own `task` tool, keeps its to-do list with `write_todos`, reads their status blocks,
and decides for itself what to do next (retry, change approach, skip, stop). There is no loop of ours around it.

What our code adds around that, so it can be seen live and cannot be talked out of the rules:

- `TeamControl` wraps the Project Manager's `task` calls: it checks the specialist name, enforces the dispatch cap,
  holds the first delegation for plan approval, limits how many run at once and for how long, turns the
  `WRITES:` line of the delegation into a write scope, records each delegation as a task, and emits the events the UI
  draws (`task_started` / `task_finished`) and the per-task commit.
- `SubAgentGuard` wraps every tool call a specialist makes: allowed paths, no `.git`, loop detection, and the
  `tool_call` / `tool_result` events.
- At the end: the report, a secret scan, and the zip.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, Literal, NotRequired, TypedDict

from agent.agents.base import ToolAllowlistMiddleware
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace, git
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from orchestrator.config import RunConfig
from orchestrator.delivery import build_zip
from orchestrator.events import EventLog
from orchestrator.guardrails import (
    MAX_BLOCKED_WRITES,
    WRITE_TOOLS,
    AgentStuck,
    CallTracker,
    WriteScope,
    tool_refusal,
)
from orchestrator.roles import ALL_ROLES, load_role
from orchestrator.runs import run_dir, write_artifact
from orchestrator.sandbox_tools import sandbox_tools_for
from orchestrator.secrets import scan_secrets
from orchestrator.status_block import parse_status
from orchestrator.task import Task, TaskLog, save_task_log

PLANNER_ROLE = "project_manager"
TASK_LOG_FILE = "task_log.json"
SPECIALISTS = tuple(r for r in ALL_ROLES if r != PLANNER_ROLE)

# The id of the delegation the current code is running inside. Set by `TeamControl` before the specialist starts and
# read by `SubAgentGuard`; it follows the asyncio task, so parallel delegations do not mix.
CURRENT_TASK: ContextVar[str | None] = ContextVar("current_task", default=None)

WRITES_RE = re.compile(r"(?im)^[ \t]*WRITES:[ \t]*(.*?)[ \t]*$")

TEAM_RULES = """\
Rules from the Project Manager's team:
- Your task message may end with a line `WRITES: <paths>`. Create or edit files only inside those paths (relative to \
the project root, for example backend/app.py). Any other path is blocked, and repeated blocked writes stop your task.
- Keep every file as short as it can be while meeting the done condition; documents stay under 80 lines. Reply with a \
short summary of what you did, not with the files' contents. Do not write your reply to a file.
- The LAST lines of your reply must be exactly this, with BOTH dash lines, not inside a code block (status is pass \
only if the task is done):
---
status: pass|fail
reason: <one line>
---"""

READ_ONLY_TOOLS = ("ls", "read_file", "grep", "glob")

# The to-do list tool's own text, replacing langchain's default. The default (about 5,000 characters) tells the model
# "for simple objectives, just complete the objective directly and do NOT use this tool", which pushes a small model
# to do the work itself instead of delegating, and it uses about a quarter of a 4096-token context on its own.
TODO_SYSTEM_PROMPT = (
    "## `write_todos`\n"
    "Keep the team's to-do list with `write_todos`: one item per piece of work, naming the specialist. Mark an item "
    "`completed` only after that specialist's reply ended with `status: pass`. Revise the list when work fails or the "
    "plan changes. Never call it twice in the same turn."
)
TODO_TOOL_DESCRIPTION = (
    "Write or update the team's to-do list. Each item has `content` (one piece of work, naming the specialist) and "
    "`status`: pending, in_progress or completed."
)

REASONS = {
    "all_passed": "All tasks passed.",
    "pm_failed": "The Project Manager reported that the work did not finish.",
    "no_final_status": "The Project Manager ended without a final status block.",
    "no_task_passed": "The Project Manager reported success, but no task passed.",
    "plan_rejected": "The plan was rejected.",
    "run_timeout": "The run hit its time limit.",
    "step_limit": "The Project Manager ran out of steps.",
}

NUDGE = (
    "You ended without delegating any work. You cannot create or edit files yourself, so nothing has been done. "
    "Delegate each item of your to-do list now with the `task` tool (include the WRITES line), then report."
)

Status = Literal["passed", "escalated", "stopped"]
ApproveFn = Callable[[dict[str, Any]], Awaitable[bool]]
# The person's decision on the finished work: {"accept": bool, "changes": str}.
ReviewFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

REVIEW_CHANGES = (
    "The person reviewed the finished work and asks for changes:\n{changes}\n\n"
    "Delegate whatever work is needed to make those changes (include the WRITES line), read the results, then report "
    "again with a short summary and a final status block."
)


class OrchestratorState(TypedDict):
    request: str
    workspace: Workspace
    run_id: str
    model: BaseChatModel
    sandbox_client: NotRequired[SandboxClient | None]
    task_log: TaskLog
    config: NotRequired[RunConfig]
    events: NotRequired[EventLog | None]
    approve: NotRequired[ApproveFn | None]
    review: NotRequired[ReviewFn | None]
    base_commit: NotRequired[str | None]
    resume_note: NotRequired[str | None]
    status: NotRequired[Status]
    end_reason: NotRequired[str | None]
    summary: NotRequired[str]


# ---------------------------------------------------------------- helpers


def role_key(name: str) -> str:
    return name.strip().lower().replace("_", "-")


NAME_TO_ROLE: dict[str, str] = {role_key(load_role(r).name): r for r in ALL_ROLES}


def resolve_role(subagent_type: str) -> str | None:
    """The role folder for a `task` call's `subagent_type`, or None for anything outside the roster."""
    role = NAME_TO_ROLE.get(role_key(subagent_type))
    return role if role in SPECIALISTS else None


def parse_writes(description: str) -> tuple[str, ...]:
    match = WRITES_RE.search(description)
    if match is None:
        return ()
    parts = re.split(r"[,\s]+", match.group(1).replace("`", "").replace('"', "").replace("'", ""))
    return tuple(p for p in parts if p and p.lower() not in ("none", "n/a", "anywhere"))


def objective_of(description: str) -> str:
    for line in description.splitlines():
        text = line.strip()
        if text and not WRITES_RE.match(line):
            return text[:200]
    return description.strip()[:200]


def result_text(result: Any) -> str:
    if isinstance(result, ToolMessage):
        content = result.content
    elif isinstance(result, Command):
        messages = (result.update or {}).get("messages") if isinstance(result.update, dict) else None
        content = messages[-1].content if messages else ""
    else:
        content = getattr(result, "content", result)  # an AIMessage, or already text
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content if p)
    return str(content)


def summarize_args(args: dict[str, Any]) -> str:
    if "file_path" in args:
        return str(args["file_path"])
    if "path" in args:
        return f"path={args['path']}"
    if "command" in args:
        return " ".join(map(str, args["command"]))[:120]
    return ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3])[:120]


def payload(t: Task) -> dict[str, Any]:
    return {
        "id": t.id, "role": t.role, "objective": t.objective, "inputs": list(t.inputs),
        "done_condition": t.done_condition, "depends_on": list(t.depends_on), "writes": list(t.writes),
        "status": t.status, "attempt": t.attempt, "reason": t.reason,
    }


def error_message(call_id: str, text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call_id, status="error")


# ---------------------------------------------------------------- the run's shared state


class TeamContext:
    def __init__(self, state: OrchestratorState) -> None:
        self.state = state
        self.cfg = state.get("config") or RunConfig()
        self.workspace = state["workspace"]
        self.run_id = state["run_id"]
        self.events = state.get("events")
        self.approve = state.get("approve")
        self.review = state.get("review")
        self.log = state["task_log"]
        self.tasks: list[Task] = self.log.tasks  # delegations so far (earlier runs of a resumed run included)
        self.by_id: dict[str, Task] = {t.id: t for t in self.tasks}
        self.scopes: dict[str, WriteScope] = {}
        self.trackers: dict[str, CallTracker] = {}
        self.tool_calls: dict[str, int] = {}
        self.role_runs: dict[str, int] = {}
        self.dispatches = 0
        self.todos: list[dict[str, Any]] = []
        self.plan_refusals = 0
        self.said: set[str] = set()
        self.approved = False
        self.rejected = False
        self._approval: asyncio.Future[bool] | None = None
        self.sem = asyncio.Semaphore(max(1, self.cfg.concurrency))
        self.t0 = time.monotonic()
        for t in self.tasks:
            self.role_runs[t.role] = self.role_runs.get(t.role, 0) + 1

    def emit(self, type_: str, **data: Any) -> None:
        if self.events is not None:
            self.events.emit(type_, **data)

    def save(self) -> None:
        self.log.tasks = self.tasks
        save_task_log(self.log, run_dir(self.workspace, self.run_id) / TASK_LOG_FILE)

    async def ensure_approved(self) -> bool:
        """Hold the first delegation until the person approves the plan (every parallel caller waits on one answer)."""
        if not self.cfg.plan_approval or self.approve is None or self.approved:
            return not self.rejected
        if self._approval is None:
            self._approval = asyncio.ensure_future(self._ask())
        return await self._approval

    async def _ask(self) -> bool:
        assert self.approve is not None
        self.emit("plan_approval_requested", todos=self.todos)
        ok = await self.approve({"todos": self.todos})
        self.emit("plan_approved" if ok else "plan_rejected")
        self.approved, self.rejected = ok, not ok
        return ok

    def changed_files(self) -> list[str]:
        """Files this run added or changed, for the review screen."""
        ws, base = self.workspace, self.state.get("base_commit")
        if not (ws.work / ".git").exists():
            return []
        self.commit_rest()
        out = git(ws.work, "diff", "--name-only", f"{base}..HEAD", check=False) if base else git(ws.work, "ls-files", check=False)
        return [line for line in out.splitlines() if line][:200]

    def would_pass(self, final_text: str) -> bool:
        verdict = parse_status(final_text) if final_text else None
        return bool(verdict and verdict.status == "pass" and "no status block" not in verdict.reason
                    and not self.rejected and any(t.status == "pass" for t in self.tasks))

    async def ask_review(self, final_text: str, round_no: int) -> dict[str, Any]:
        """Pause before the zip is built and ask the person whether anything should change."""
        assert self.review is not None
        self.emit("review_requested", round=round_no, summary=strip_status_block(final_text)[:1500], files=self.changed_files())
        decision = await self.review({"round": round_no})
        if decision.get("accept"):
            self.emit("review_accepted", round=round_no)
        else:
            self.emit("review_changes_requested", round=round_no, text=str(decision.get("changes", ""))[:2000])
        return decision

    def commit_task(self, task: Task) -> None:
        """Commit what this delegation wrote: only its declared paths, so parallel tasks get separate commits."""
        ws = self.workspace
        if not (ws.work / ".git").exists():
            return
        try:
            if task.writes:
                for spec in task.writes:
                    git(ws.work, "add", "-A", "--", spec.lstrip("/"), check=False)
            else:
                git(ws.work, "add", "-A")
            if git(ws.work, "diff", "--cached", "--name-only"):
                git(ws.work, "commit", "-q", "-m", f"{task.role}: {task.objective[:60]} [{task.id}]")
        except RuntimeError as exc:
            self.emit("plan_warning", message=f"could not commit {task.id}: {exc}"[:200])

    def commit_rest(self) -> None:
        ws = self.workspace
        if (ws.work / ".git").exists():
            try:
                ws.commit_all(f"run {self.run_id}: remaining changes")
            except RuntimeError as exc:
                self.emit("plan_warning", message=f"could not commit the remaining changes: {exc}"[:200])


# ---------------------------------------------------------------- middleware


class SubAgentGuard(AgentMiddleware[Any, Any, Any]):
    """Wraps every tool call a specialist makes."""

    def __init__(self, ctx: TeamContext, role: str) -> None:
        super().__init__()
        self.ctx = ctx
        self.role = role

    @property
    def name(self) -> str:
        return f"SubAgentGuard-{self.role}"

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ) -> ToolMessage | Command[Any]:
        ctx, call = self.ctx, request.tool_call
        tid = CURRENT_TASK.get()
        name, args = call["name"], call.get("args") or {}
        scope = ctx.scopes.get(tid or "") or WriteScope()
        refusal = tool_refusal(scope, name, args)
        if refusal is not None:
            path, reason = refusal
            scope.blocked += 1
            ctx.emit(
                "guardrail_hit", kind="write_blocked" if name in WRITE_TOOLS else "path_blocked",
                task_id=tid, role=self.role, tool=name, path=path, reason=reason,
            )
            if scope.blocked >= MAX_BLOCKED_WRITES:
                raise AgentStuck(f"tried to use a blocked path {scope.blocked} times")
            return error_message(
                (call["id"] or ""), f"Blocked: {reason}. Do not retry this path; write only inside your task's scope."
            )
        tracker = ctx.trackers.get(tid or "")
        if tracker is not None:
            tracker.note(name, args)
        ctx.emit("tool_call", task_id=tid, role=self.role, tool=name, summary=summarize_args(args), error=False)
        result = await handler(request)
        text = result_text(result)
        failed = isinstance(result, ToolMessage) and result.status == "error"
        ctx.emit(
            "tool_result", task_id=tid, role=self.role, tool=name,
            summary=(text.strip().splitlines() or [""])[0][:120], error=failed,
        )
        if tid:
            ctx.tool_calls[tid] = ctx.tool_calls.get(tid, 0) + 1
        return result


class TeamControl(AgentMiddleware[Any, Any, Any]):
    """Wraps the Project Manager's `task` and `write_todos` calls."""

    def __init__(self, ctx: TeamContext) -> None:
        super().__init__()
        self.ctx = ctx

    @property
    def name(self) -> str:
        return "TeamControl"

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        self.say_once(request)
        if call["name"] == "write_todos":
            result = await handler(request)
            todos = (call.get("args") or {}).get("todos")
            if isinstance(todos, list):
                self.ctx.todos = [
                    {"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                    for t in todos if isinstance(t, dict)
                ]
                self.ctx.emit("todos_updated", todos=self.ctx.todos)
            return result
        if call["name"] != "task":
            return await handler(request)
        return await self.delegate(request, handler)

    def say_once(self, request: ToolCallRequest) -> None:
        """Emit what the Project Manager wrote alongside this tool call (its reasoning), once per message."""
        messages = getattr(request.state, "get", lambda *_: None)("messages") if isinstance(request.state, dict) else None
        last = messages[-1] if messages else None
        text = result_text(last).strip() if last is not None else ""
        key = getattr(last, "id", None) or text
        if not text or key in self.ctx.said:
            return
        self.ctx.said.add(key)
        self.ctx.emit("pm_said", text=text[:1500])

    async def delegate(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ) -> ToolMessage | Command[Any]:
        ctx, call = self.ctx, request.tool_call
        args = call.get("args") or {}
        description = str(args.get("description", ""))
        role = resolve_role(str(args.get("subagent_type", "")))
        if role is None:
            names = ", ".join(load_role(r).name for r in SPECIALISTS)
            return error_message((call["id"] or ""), f"Unknown sub-agent {args.get('subagent_type')!r}. Use one of: {names}.")
        if ctx.cfg.require_plan and not ctx.todos:
            if ctx.plan_refusals < ctx.cfg.max_plan_refusals:
                ctx.plan_refusals += 1
                ctx.emit("plan_required", message="The Project Manager tried to delegate before writing a plan; asked it to plan first.")
                return error_message(
                    (call["id"] or ""),
                    "Plan first. Call `write_todos` now with one item per piece of work (each naming the specialist), "
                    "then delegate each item with `task`.",
                )
            ctx.emit("plan_warning", message="The Project Manager delegated without writing a plan.")
        if ctx.dispatches >= ctx.cfg.max_total_dispatches:
            ctx.emit("guardrail_hit", kind="dispatch_cap", reason=f"limit of {ctx.cfg.max_total_dispatches} delegations")
            return error_message(
                (call["id"] or ""),
                "Delegation limit reached. Delegate nothing more: end now with a short summary and a final status block "
                "(status: fail unless every needed task already passed).",
            )
        if not await ctx.ensure_approved():
            return error_message(
                (call["id"] or ""), "The person rejected the plan. Delegate nothing: end with status: fail, reason: plan rejected."
            )
        async with ctx.sem:
            return await self._run(request, handler, role, description)

    async def _run(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
        role: str, description: str,
    ) -> ToolMessage | Command[Any]:
        ctx, call = self.ctx, request.tool_call
        ctx.dispatches += 1
        ctx.role_runs[role] = ctx.role_runs.get(role, 0) + 1
        task = Task(
            id=uuid.uuid4().hex[:8], role=role, objective=objective_of(description), inputs=(), done_condition="",
            status="in_progress", attempt=ctx.role_runs[role], writes=parse_writes(description),
        )
        ctx.tasks.append(task)
        ctx.by_id[task.id] = task
        ctx.scopes[task.id] = WriteScope(task.writes, ctx.cfg.max_file_bytes, ctx.cfg.max_files_per_task)
        ctx.trackers[task.id] = CallTracker(ctx.cfg.max_tool_calls_per_task)
        ctx.save()
        ctx.emit("task_started", task=payload(task))
        CURRENT_TASK.set(task.id)

        error = ""
        text = ""
        result: ToolMessage | Command[Any] | None = None
        try:
            result = await asyncio.wait_for(handler(request), ctx.cfg.task_timeout_s)
            text = result_text(result)
        except AgentStuck as exc:
            error = f"stopped: the agent {exc}"
            ctx.emit("guardrail_hit", kind="agent_stuck", task_id=task.id, role=role, reason=error)
        except TimeoutError:
            error = f"timed out after {ctx.cfg.task_timeout_s:g}s"
            ctx.emit("guardrail_hit", kind="task_timeout", task_id=task.id, role=role, reason=error)
        except GraphRecursionError:
            error = "ran out of steps"
        except Exception as exc:  # noqa: BLE001 (a failing specialist is a failed task, not a crashed run)
            error = f"{type(exc).__name__}: {exc}"[:300]

        artifact = text or f"(no result: {error or 'the agent replied with nothing'})"
        write_artifact(ctx.workspace, ctx.run_id, f"{task.id}.md", artifact)
        write_artifact(ctx.workspace, ctx.run_id, f"{task.id}.attempt{task.attempt}.md", artifact)
        verdict = parse_status(artifact)
        status, reason = verdict.status, verdict.reason
        if error:
            status, reason = "fail", error
        task.status, task.reason = status, reason
        if status == "pass":
            ctx.commit_task(task)
        ctx.save()
        ctx.emit(
            "task_finished", task=payload(task), verdict=status, will_retry=status != "pass",
            artifact=f"{task.id}.md", tool_calls=ctx.tool_calls.get(task.id, 0),
        )
        if error:
            return error_message((call["id"] or ""), f"FAILED: the specialist {error}")
        assert result is not None
        return result


# ---------------------------------------------------------------- building the team


def pm_system_prompt() -> str:
    return load_role(PLANNER_ROLE).prompt


def subagent_specs(ctx: TeamContext, client: SandboxClient | None) -> list[dict[str, Any]]:
    project = ctx.workspace.path.name
    specs: list[dict[str, Any]] = []
    for role in SPECIALISTS:
        cfg = load_role(role)
        tools = sandbox_tools_for(role, client, project) if client is not None else []
        specs.append({
            "name": cfg.name,
            "description": cfg.description,
            "system_prompt": f"{cfg.prompt}\n\n{TEAM_RULES}",
            "tools": tools,
            "middleware": [ToolAllowlistMiddleware(cfg.tools), SubAgentGuard(ctx, role)],
        })
    # deepagents adds a `general-purpose` sub-agent with every tool unless one with that name is given. This one is
    # read-only and `TeamControl` refuses to delegate to it, so it cannot be used to go around the specialists.
    specs.append({
        "name": "general-purpose",
        "description": "NOT AVAILABLE. Do not use this. Delegate to one of the named specialists instead.",
        "system_prompt": "You look things up in the project and report what you find. You cannot change files.",
        "tools": [],
        "middleware": [ToolAllowlistMiddleware(READ_ONLY_TOOLS), SubAgentGuard(ctx, "general-purpose")],
    })
    return specs


def build_team(ctx: TeamContext) -> Any:
    state = ctx.state
    pm = load_role(PLANNER_ROLE)
    return create_deep_agent(
        model=state["model"],
        system_prompt=pm_system_prompt(),
        subagents=subagent_specs(ctx, state.get("sandbox_client")),  # type: ignore[arg-type]
        middleware=[
            TodoListMiddleware(system_prompt=TODO_SYSTEM_PROMPT, tool_description=TODO_TOOL_DESCRIPTION),
            ToolAllowlistMiddleware(pm.tools),
            TeamControl(ctx),
        ],
        backend=FilesystemBackend(root_dir=ctx.workspace.work.resolve(), virtual_mode=True),
        name=pm.name,
    )


def first_message(state: OrchestratorState) -> str:
    parts = [f"Request:\n{state['request']}"]
    if note := state.get("resume_note"):
        parts.append(note)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- running and finishing


def report_markdown(ctx: TeamContext, status: Status, reason: str, summary: str, delivery: str) -> str:
    state = ctx.state
    reason_text = REASONS.get(reason, reason)
    lines = [
        f"# Run {ctx.run_id}: {status}", "", f"**Request:** {state['request']}", "", f"**Result:** {reason_text}", "",
    ]
    if summary:
        lines += ["## Summary", "", summary.strip(), ""]
    lines += ["## Delegated work", "", "| Specialist | Task | Result | Try | Reason |", "|---|---|---|---|---|"]
    for t in ctx.tasks:
        lines.append(
            f"| {t.role} | {t.objective.replace('|', '/')} | {t.status} | {t.attempt} | {t.reason.replace('|', '/')} |"
        )
    failing = [t for t in ctx.tasks if t.status == "fail"]
    if failing:
        lines += ["", "## What did not pass", ""]
        lines += [f"- **{t.role}** ({t.id}): {t.reason or t.status}. Evidence: `{t.id}.attempt{t.attempt}.md`." for t in failing]
    base, ws = state.get("base_commit"), ctx.workspace
    stat = git(ws.work, "diff", "--stat", f"{base}..HEAD", check=False) if base and (ws.work / ".git").exists() else ""
    lines += ["", "## Files changed", "", "```", stat or "(no committed changes)", "```"]
    hits = [e for e in (ctx.events.since(0) if ctx.events else []) if e["type"] == "guardrail_hit"]
    if hits:
        lines += ["", "## Guardrails that fired", ""]
        lines += [f"- {h['kind']}: {h.get('reason', '')} {h.get('path', '')}".rstrip() for h in hits]
    lines += ["", "## Delivery", "", delivery, ""]
    return "\n".join(lines)


def strip_status_block(text: str) -> str:
    return re.sub(r"(?s)\n*(?:```[A-Za-z]*\n)?-{3}\s*\nstatus:.*\Z|\n*```[A-Za-z]*\nstatus:.*\Z", "", text).strip()


def finish(ctx: TeamContext, final_text: str, error_reason: str | None) -> tuple[Status, str, str]:
    """Decide the outcome, write the report, scan, build the zip, emit run_finished. Returns (status, reason, summary)."""
    ws = ctx.workspace
    ctx.commit_rest()
    status: Status
    verdict = parse_status(final_text) if final_text else None
    summary = strip_status_block(final_text) if final_text else ""
    if ctx.rejected:
        status, reason = "stopped", "plan_rejected"
    elif error_reason:
        status, reason = "escalated", error_reason
    elif verdict is None or "no status block" in verdict.reason:
        status, reason = "escalated", "no_final_status"
    elif verdict.status == "fail":
        status, reason = "escalated", "pm_failed"
        summary = f"{summary}\n\nReason given: {verdict.reason}".strip()
    elif not any(t.status == "pass" for t in ctx.tasks):
        status, reason = "escalated", "no_task_passed"
    else:
        status, reason = "passed", "all_passed"

    delivery = "No zip was built because the run did not finish. A partial zip can be requested."
    findings = []
    if status == "passed":
        findings = scan_secrets(ws.work)
        if findings:
            shown = [{"path": f.path, "line": f.line, "kind": f.kind} for f in findings[:20]]
            ctx.emit("guardrail_hit", kind="secret_scan", reason=f"{len(findings)} possible secret(s) found", findings=shown)
            delivery = "The zip was **not built**: the secret scan found possible secrets:\n\n" + "\n".join(
                f"- `{f.path}` line {f.line}: {f.kind}" for f in findings[:20]
            )
        else:
            delivery = "`delivery.zip` (project files at the root, this report and the artifacts under `docs/orchestrator/`)."
    write_artifact(ws, ctx.run_id, "report.md", report_markdown(ctx, status, reason, summary, delivery))
    ctx.emit("report_ready", path="report.md")
    if status == "passed" and not findings:
        count = build_zip(ws.work, run_dir(ws, ctx.run_id), run_dir(ws, ctx.run_id) / "delivery.zip")[1]
        ctx.emit("delivery_ready", path="delivery.zip", files=count, partial=False)
    counts: dict[str, int] = {}
    for t in ctx.tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    ctx.save()
    ctx.emit(
        "run_finished", status=status, reason=reason, message=REASONS.get(reason, reason), tasks=counts,
        dispatches=ctx.dispatches, seconds=round(time.monotonic() - ctx.t0, 1), summary=summary[:1500],
    )
    return status, reason, summary


async def run_team(state: OrchestratorState) -> OrchestratorState:
    """Run the Project Manager to its end, then finish. Raises only on cancellation or an unexpected crash."""
    ctx = TeamContext(state)
    ctx.emit("plan_started")
    agent = build_team(ctx)
    final_text, error_reason = "", None
    async def invoke(messages: list[Any]) -> Any:
        return await agent.ainvoke({"messages": messages}, config={"recursion_limit": ctx.cfg.max_pm_steps})

    async def drive() -> str:
        result = await invoke([{"role": "user", "content": first_message(state)}])
        for _ in range(ctx.cfg.max_nudges):
            if ctx.dispatches > 0 or ctx.rejected:
                break
            ctx.emit("pm_nudged", message="The Project Manager ended without delegating anything; asking it to delegate.")
            result = await invoke([*result["messages"], HumanMessage(content=NUDGE)])
        final = result_text(result["messages"][-1])
        # Final review: before anything is delivered, ask whether the person wants changes.
        for round_no in range(1, ctx.cfg.max_review_rounds + 1):
            if not (ctx.cfg.final_review and ctx.review is not None and ctx.would_pass(final)):
                break
            decision = await ctx.ask_review(final, round_no)
            if decision.get("accept"):
                break
            changes = str(decision.get("changes", "")).strip() or "Please check the work again and improve it."
            result = await invoke([*result["messages"], HumanMessage(content=REVIEW_CHANGES.format(changes=changes))])
            final = result_text(result["messages"][-1])
        return final

    try:
        final_text = await asyncio.wait_for(drive(), ctx.cfg.run_timeout_s)
    except TimeoutError:
        error_reason = "run_timeout"
    except GraphRecursionError:
        error_reason = "step_limit"
    with contextlib.suppress(Exception):
        ctx.save()
    status, reason, summary = finish(ctx, final_text, error_reason)
    return {**state, "status": status, "end_reason": reason, "summary": summary}  # type: ignore[typeddict-item]
