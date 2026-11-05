"""Guardrails that are enforced in code, never only in a prompt.

- `WriteScope`: a task may only write inside the paths its plan declared, never
  into `.git`, never outside the workspace, never a real `.env`, and within a size/file-count budget.
- `writes_overlap`: the scheduler uses it to refuse running two tasks at once when their write areas overlap.
- `machine_verdict`: for roles with an objective check (QA's tests, DevOps's build) the status is the real exit
  code of the tool, not the model's say-so.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

WRITE_TOOLS = ("write_file", "edit_file")
# Any tool that takes a path may not touch `.git`: a blocked agent was seen listing every object folder in it.
PATH_ARGS = ("file_path", "path")
_ENV_OK_SUFFIXES = (".example", ".sample", ".template")



def normalize_path(raw: str) -> str | None:
    """A workspace-relative POSIX path, or None when it tries to escape (`..`)."""
    parts = [p for p in PurePosixPath("/" + raw.strip().lstrip("/")).parts if p != "/"]
    if any(p == ".." for p in parts):
        return None
    return "/".join(p for p in parts if p != ".")


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


def tool_refusal(scope: WriteScope, name: str, args: dict[str, Any]) -> tuple[str, str] | None:
    """(path, reason) when a tool call must be blocked, else None (and an allowed write is recorded).

    - any tool: never touches `.git` (a blocked agent was seen listing every object folder in it)
    - write_file / edit_file: only inside the task's declared paths, never a real `.env`, within the size budgets"""
    if name not in WRITE_TOOLS:
        for key in PATH_ARGS:
            value = args.get(key)
            normalized = normalize_path(value) if isinstance(value, str) else None
            if normalized is not None and ".git" in normalized.split("/"):
                return str(value), "the .git folder is not available"
        return None
    path = str(args.get("file_path") or args.get("path") or "")
    body = args.get("content") if name == "write_file" else args.get("new_string", "")
    reason = scope.check(path, len(str(body or "").encode("utf-8")))
    if reason is None:
        scope.record(path)
        return None
    return path, reason


class CallTracker:
    """Per-task loop detection: the same call over and over, too many calls, too many blocked writes."""

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.calls = 0
        self.repeats: dict[str, int] = {}

    def note(self, name: str, args: dict[str, Any]) -> None:
        self.calls += 1
        if self.calls > self.max_calls:
            raise AgentStuck(f"used more than {self.max_calls} tool calls")
        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)[:400]}"
        self.repeats[key] = self.repeats.get(key, 0) + 1
        if self.repeats[key] > MAX_REPEATED_CALLS:
            raise AgentStuck(f"repeated the same {name} call {self.repeats[key]} times")
