"""Task and TaskLog: the record of one run's delegations, persisted as `task_log.json`.

A `Task` is one delegation to a specialist, one *attempt* at a piece of work. A retry is a new task whose `retry_of`
names the attempt it follows, so every attempt, its reason and its evidence stay on record. `depends_on` names the
tasks that had to pass before this one could start (checked in code when the delegation is made).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "pass", "fail"]
# What kind of failure it was, so a retry can be handled accordingly (infrastructure failures are retried after a pause).
FailureKind = Literal["", "agent", "invalid_output", "guardrail", "infrastructure", "evaluation"]
TUPLE_FIELDS = ("depends_on", "writes", "acceptance")


@dataclass
class Task:
    id: str
    role: str
    objective: str
    status: TaskStatus = "pending"
    attempt: int = 1  # the try number for this piece of work (a retry is the previous attempt + 1)
    retry_of: str = ""  # the failed task this one follows
    depends_on: tuple[str, ...] = ()
    # Paths/globs the task may write. Empty = anywhere in work/.
    writes: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()  # what must be true when it is done, as the Project Manager wrote it
    brief: str = ""  # the instruction the specialist was given
    reason: str = ""
    files: list[str] = field(default_factory=list)  # the files it really created, changed or deleted
    failure_kind: FailureKind = ""
    # What the independent check found (files really written, test exit codes...), whatever the specialist claimed.
    evidence: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)  # ids of the few-shot examples this try was given


@dataclass
class TaskLog:
    run_id: str
    request: str
    tasks: list[Task]


def save_task_log(log: TaskLog, path: Path) -> None:
    path.write_text(json.dumps(asdict(log), indent=2), encoding="utf-8")


def load_task_log(path: Path) -> TaskLog:
    data = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Task)}

    def task(raw: dict[str, Any]) -> Task:  # keys from older logs that no longer exist are ignored
        values = {k: v for k, v in raw.items() if k in known}
        for key in TUPLE_FIELDS:
            values[key] = tuple(values.get(key, ()))
        return Task(**values)

    return TaskLog(run_id=data["run_id"], request=data["request"], tasks=[task(t) for t in data["tasks"]])


def mark_interrupted(log: TaskLog) -> None:
    """A delegation that was still running when the run was cut off counts as failed."""
    for t in log.tasks:
        if t.status == "in_progress":
            t.status, t.reason, t.failure_kind = "fail", "interrupted before it finished", "infrastructure"


def unresolved(tasks: list[Task]) -> list[Task]:
    """Failed work nobody fixed: no later attempt of it passed, and no later task by the same specialist passed."""

    def fixed(t: Task) -> bool:
        for later in tasks[tasks.index(t) + 1:]:
            if later.status == "pass" and (later.retry_of == t.id or later.role == t.role):
                return True
            if later.retry_of == t.id and fixed(later):
                return True
        return False

    return [t for t in tasks if t.status in ("fail", "in_progress") and not fixed(t)]
