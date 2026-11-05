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
from collections.abc import Sequence
from pathlib import Path

from agent.agents.base import ToolAllowlistMiddleware
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

from orchestrator.roles import ALL_ROLES, load_role

_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


class PlannedTask(BaseModel):
    role: str
    objective: str
    inputs: list[str] = []
    done_condition: str


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

    return tasks


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
    config = load_role(role)
    backend = FilesystemBackend(root_dir=workspace.resolve(), virtual_mode=True)
    agent = create_deep_agent(
        model=model,
        tools=list(extra_tools),
        system_prompt=config.prompt,
        middleware=[ToolAllowlistMiddleware(config.tools)],
        backend=backend,
        name=config.name,
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": objective}]})
    return result["messages"][-1].content
