"""Guardrails that are enforced in code, never only in a prompt.

- `WriteScope` + `WriteScopeMiddleware`: a task may only write inside the paths its plan declared, never
  into `.git`, never outside the workspace, never a real `.env`, and within a size/file-count budget.
- `writes_overlap`: the scheduler uses it to refuse running two tasks at once when their write areas overlap.
- `machine_verdict`: for roles with an objective check (QA's tests, DevOps's build) the status is the real exit
  code of the tool, not the model's say-so.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

WRITE_TOOLS = ("write_file", "edit_file")
_ENV_OK_SUFFIXES = (".example", ".sample", ".template")
_WILDCARDS = "*?["

# role -> the sandbox tool whose real exit code decides the status
MACHINE_CHECKS: dict[str, str] = {"qa_engineer": "run_tests", "devops_engineer": "run_build"}
_EXIT_RE = re.compile(r"\Aexit (-?\d+)")


def normalize_path(raw: str) -> str | None:
    """A workspace-relative POSIX path, or None when it tries to escape (`..`)."""
    parts = [p for p in PurePosixPath("/" + raw.strip().lstrip("/")).parts if p != "/"]
    if any(p == ".." for p in parts):
        return None
    return "/".join(p for p in parts if p != ".")


def _prefix(glob: str) -> str:
    g = glob.strip().lstrip("/")
    cut = min((g.find(c) for c in _WILDCARDS if c in g), default=len(g))
    return g[:cut]


def path_matches(path: str, globs: tuple[str, ...]) -> bool:
    if not globs:
        return True
    for raw in globs:
        g = raw.strip().lstrip("/")
        if g.endswith(("/**", "/")):
            base = g.rstrip("*").rstrip("/")
            if path == base or path.startswith(base + "/"):
                return True
        elif path == g or fnmatch.fnmatchcase(path, g):
            return True
    return False


def writes_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Conservative: an empty scope means "anywhere", so it overlaps everything."""
    if not a or not b:
        return True
    return any(_prefix(x).startswith(_prefix(y)) or _prefix(y).startswith(_prefix(x)) for x in a for y in b)


def forbidden_reason(path: str) -> str | None:
    parts = path.split("/")
    if ".git" in parts:
        return "writing inside .git is never allowed"
    name = parts[-1]
    if name == ".env" or (name.startswith(".env.") and not name.endswith(_ENV_OK_SUFFIXES)):
        return "real .env files are never written (use .env.example)"
    return None


MAX_BLOCKED_WRITES = 3  # a task that keeps writing outside its scope is stuck, not careless
MAX_REPEATED_CALLS = 3  # the same tool call with the same arguments more than this many times is a loop


class AgentStuck(Exception):
    """The agent is looping or ignoring a guardrail; the task is stopped and counts as a failed attempt."""


@dataclass
class WriteScope:
    globs: tuple[str, ...] = ()
    max_file_bytes: int = 200_000
    max_files: int = 30
    written: set[str] = field(default_factory=set)
    blocked: int = 0

    def check(self, raw_path: str, content_bytes: int) -> str | None:
        """None when the write is allowed, else the reason it is blocked."""
        path = normalize_path(raw_path)
        if path is None or not path:
            return "path escapes the workspace"
        if reason := forbidden_reason(path):
            return reason
        if not path_matches(path, self.globs):
            return f"outside this task's write scope ({', '.join(self.globs)})"
        if content_bytes > self.max_file_bytes:
            return f"file is {content_bytes} bytes; the limit is {self.max_file_bytes}"
        if path not in self.written and len(self.written) >= self.max_files:
            return f"more than {self.max_files} files in one task"
        return None

    def record(self, raw_path: str) -> None:
        if (path := normalize_path(raw_path)) is not None:
            self.written.add(path)


BlockHandler = Callable[[str, str, str], None]  # (tool, path, reason)


class WriteScopeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Refuses a write/edit call that breaks the task's `WriteScope` (the model sees the reason)."""

    def __init__(self, scope: WriteScope, on_block: BlockHandler | None = None) -> None:
        super().__init__()
        self.scope = scope
        self._on_block = on_block

    @property
    def name(self) -> str:
        return "WriteScopeMiddleware"

    def _refusal(self, request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        if call["name"] not in WRITE_TOOLS:
            return None
        args = call.get("args") or {}
        path = str(args.get("file_path") or args.get("path") or "")
        body = args.get("content") if call["name"] == "write_file" else args.get("new_string", "")
        reason = self.scope.check(path, len(str(body or "").encode("utf-8")))
        if reason is None:
            self.scope.record(path)
            return None
        self.scope.blocked += 1
        if self._on_block is not None:
            self._on_block(call["name"], path, reason)
        return ToolMessage(
            content=f"Blocked: {reason}. Do not retry this path; write only inside your task's scope.",
            tool_call_id=call["id"],
            status="error",
        )

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]]
    ) -> ToolMessage | Command[Any]:
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ) -> ToolMessage | Command[Any]:
        return self._refusal(request) or await handler(request)


@dataclass(frozen=True)
class ToolRecord:
    name: str
    args: dict[str, Any]
    output: str = ""
    error: bool = False


def machine_verdict(role: str, calls: list[ToolRecord]) -> tuple[bool, str] | None:
    """For QA/DevOps: (ok, reason) from the last real run of their sandbox tool; None when the role has no check.

    No run at all is a failure: a pass is never trusted without an actual test/build run."""
    tool = MACHINE_CHECKS.get(role)
    if tool is None:
        return None
    runs = [c for c in calls if c.name == tool and not c.error]
    if not runs:
        return False, f"{tool} was never run, so a pass cannot be trusted"
    match = _EXIT_RE.match(runs[-1].output)
    if match is None:
        return False, f"{tool} returned no exit code"
    code = int(match.group(1))
    return (code == 0), f"{tool} exited {code}"
