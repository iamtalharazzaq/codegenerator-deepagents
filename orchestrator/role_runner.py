"""Single-role agent runner and plan parsing.

`parse_plan` extracts and validates a JSON task list from an LLM's free-form reply (the
output of a planning prompt). `run_role` builds and runs a single `deepagents` agent for
one role — no nested sub-agents — and returns its final reply. These are the building
blocks the orchestration loop (Task 8) wires together: it calls `run_role` once per task
instead of letting deepagents nest roles itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.agents.base import ToolAllowlistMiddleware
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

from orchestrator.guardrails import (
    MAX_BLOCKED_WRITES,
    MAX_REPEATED_CALLS,
    AgentStuck,
    BlockHandler,
    ToolRecord,
    WriteScope,
    WriteScopeMiddleware,
)
from orchestrator.roles import ALL_ROLES, load_role

_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


class PlannedTask(BaseModel):
    role: str
    objective: str
    inputs: list[str] = []
    done_condition: str
    # The Project Manager's to-do list is a graph: `key` names a task inside this plan, `depends_on` lists keys of
    # this plan or ids of tasks that already exist, `writes` is where the task may write, `replaces` is the id of
    # an open/failed task this one continues (so its attempt count follows the work, not the role).
    key: str = ""
    depends_on: list[str] = []
    writes: list[str] = []
    replaces: str | None = None


def parse_plan(text: str) -> list[PlannedTask]:
    """Extract the last fenced ```json block from `text` and validate it as a list of
    `PlannedTask`s. Raises `ValueError` if no such block is found, the JSON doesn't parse
    or match `PlannedTask`, or any `role` isn't in `ALL_ROLES`.
    """
    matches = _JSON_FENCE_RE.findall(text)
    if not matches:
        raise ValueError("no ```json block found in the plan text")
    raw = matches[-1]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json in plan block: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("plan json must be a list of tasks")  # noqa: TRY004 (ValueError is the contract here)

    try:
        tasks = [PlannedTask.model_validate(item) for item in data]
    except ValidationError as exc:
        raise ValueError(f"plan json does not match the expected task shape: {exc}") from exc

    for task in tasks:
        if task.role not in ALL_ROLES:
            raise ValueError(f"unknown role {task.role!r}; expected one of {ALL_ROLES}")

    _check_keys_and_cycles(tasks)
    return tasks


def _check_keys_and_cycles(tasks: list[PlannedTask]) -> None:
    keys = [t.key for t in tasks if t.key]
    if len(keys) != len(set(keys)):
        raise ValueError("plan has duplicate task keys")
    deps = {t.key: [d for d in t.depends_on if d in keys] for t in tasks if t.key}
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished

    def visit(key: str) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise ValueError(f"plan has a dependency cycle through {key!r}")
        state[key] = 1
        for dep in deps[key]:
            visit(dep)
        state[key] = 2

    for key in deps:
        visit(key)


def plan_summary(text: str, limit: int = 300) -> str:
    """The Project Manager's own words before the JSON block, used as the plan's stated reason."""
    head = text.split("```json", 1)[0].strip()
    return head[:limit]


@dataclass
class RoleRun:
    text: str
    calls: list[ToolRecord] = field(default_factory=list)


ToolHook = Callable[[str, ToolRecord], None]  # ("call" | "result", record)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content if p)
    return str(content)


def _messages(update: Any) -> list[Any]:
    messages = update.get("messages") if isinstance(update, dict) else None
    messages = getattr(messages, "value", messages)  # langgraph may wrap it in Overwrite
    return list(messages) if isinstance(messages, list | tuple) else []


async def run_role_traced(
    role: str,
    objective: str,
    model: BaseChatModel,
    workspace: Path,
    extra_tools: Sequence[BaseTool] = (),
    *,
    write_scope: WriteScope | None = None,
    on_block: BlockHandler | None = None,
    on_tool: ToolHook | None = None,
    max_steps: int = 60,
) -> RoleRun:
    """Like `run_role`, but streams the agent so every tool call is observed (and recorded for the machine checks),
    and enforces a write scope. Returns the final reply plus the tool calls made."""
    config = load_role(role)
    backend = FilesystemBackend(root_dir=workspace.resolve(), virtual_mode=True)
    middleware: list[Any] = [ToolAllowlistMiddleware(config.tools)]
    if write_scope is not None:
        middleware.append(WriteScopeMiddleware(write_scope, on_block))
    agent = create_deep_agent(
        model=model,
        tools=list(extra_tools),
        system_prompt=config.prompt,
        middleware=middleware,
        backend=backend,
        name=config.name,
    )
    pending: dict[str, ToolRecord] = {}
    calls: list[ToolRecord] = []
    repeats: dict[str, int] = {}
    final = ""
    stream = agent.astream(
        {"messages": [{"role": "user", "content": objective}]},
        config={"recursion_limit": max_steps},  # a step budget: a looping agent cannot run forever
        stream_mode="updates",
    )
    async for chunk in stream:
        for update in chunk.values():
            for message in _messages(update):
                if isinstance(message, AIMessage):
                    if message.tool_calls:
                        for call in message.tool_calls:
                            record = ToolRecord(call["name"], dict(call.get("args") or {}))
                            pending[call["id"] or ""] = record
                            if on_tool is not None:
                                on_tool("call", record)
                    else:
                        final = _text(message.content)
                elif isinstance(message, ToolMessage):
                    started = pending.pop(message.tool_call_id or "", None)
                    name = started.name if started else (message.name or "?")
                    record = ToolRecord(
                        name, started.args if started else {}, _text(message.content), message.status == "error"
                    )
                    calls.append(record)
                    if on_tool is not None:
                        on_tool("result", record)
                    key = f"{record.name}:{json.dumps(record.args, sort_keys=True, default=str)[:400]}"
                    repeats[key] = repeats.get(key, 0) + 1
                    if repeats[key] > MAX_REPEATED_CALLS:
                        raise AgentStuck(f"repeated the same {record.name} call {repeats[key]} times")
                    if write_scope is not None and write_scope.blocked >= MAX_BLOCKED_WRITES:
                        raise AgentStuck(f"tried to write outside its scope {write_scope.blocked} times")
    return RoleRun(final, calls)


async def run_role(
    role: str,
    objective: str,
    model: BaseChatModel,
    workspace: Path,
    extra_tools: Sequence[BaseTool] = (),
) -> str:
    """Build a single-role `deepagents` agent (no `subagents=`) and run one turn with
    `objective` as the human message. Returns the final message's content.
    """
    return (await run_role_traced(role, objective, model, workspace, extra_tools)).text
