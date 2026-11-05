"""Task and TaskLog schema with JSON persistence.

A `TaskLog` is the orchestrator's working state for one run: the original request plus
the list of `Task`s the plan broke it into. It is persisted as a JSON file so the
orchestration loop (later tasks) can resume or inspect progress between steps, and so a
human can read it directly as a debugging artifact.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

TaskStatus = Literal["pending", "in_progress", "pass", "fail", "escalated", "blocked", "superseded"]


@dataclass
class Task:
    id: str
    role: str
    objective: str
    inputs: tuple[str, ...]
    done_condition: str
    status: TaskStatus = "pending"
    attempt: int = 0
    depends_on: tuple[str, ...] = ()
    # Paths/globs the task may write. Empty = anywhere in work/ (and then it never runs alongside another task).
    writes: tuple[str, ...] = ()
    # Why the task last failed / was superseded / blocked; and every failure reason so far (repeat detection).
    reason: str = ""
    reasons: list[str] = field(default_factory=list)


@dataclass
class TaskLog:
    run_id: str
    request: str
    tasks: list[Task]
    # The failure the planner has not yet replanned around (kept so a resumed run knows what went wrong).
    last_failure: str | None = None


def save_task_log(log: TaskLog, path: Path) -> None:
    data = asdict(log)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_task_log(path: Path) -> TaskLog:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = [
        Task(
            id=t["id"],
            role=t["role"],
            objective=t["objective"],
            inputs=tuple(t["inputs"]),
            done_condition=t["done_condition"],
            status=t["status"],
            attempt=t["attempt"],
            depends_on=tuple(t["depends_on"]),
            writes=tuple(t.get("writes", ())),
            reason=t.get("reason", ""),
            reasons=list(t.get("reasons", [])),
        )
        for t in data["tasks"]
    ]
    return TaskLog(run_id=data["run_id"], request=data["request"], tasks=tasks, last_failure=data.get("last_failure"))
