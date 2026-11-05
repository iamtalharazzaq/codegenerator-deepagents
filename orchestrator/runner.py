"""Starting, resuming and running a run: the pieces the CLI and the web service share.

- `prepare_workspace`: a git repo in `work/` and a `run/<run_id>` branch; returns the base commit for the report.
- `meta.json` per run: what the run list shows (status, request, project), updated as the run moves.
- `reopen_for_resume`: puts an escalated/interrupted run back in a runnable state.
- `run_graph`: invokes the graph with a recursion limit that fits a full run, and makes sure a run *always* ends
  with a `run_finished` event, even when something unexpected raises.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Literal

from agent.tools.workspace import Workspace, git

from orchestrator.events import EventLog
from orchestrator.graph import OrchestratorState, build_graph
from orchestrator.task import TaskLog

RECURSION_LIMIT = 1000  # a run is far longer than langgraph's default of 25 steps
META_FILE = "meta.json"


def prepare_workspace(ws: Workspace, run_id: str) -> str | None:
    """Make sure `work/` is a git repo and put the run on its own branch. Returns the base commit."""
    ws.create()
    if not (ws.work / ".git").exists():
        ws.init_git()
    try:
        base = git(ws.work, "rev-parse", "HEAD")
        ws.branch(f"run/{run_id}")
    except RuntimeError:
        return None
    return base


def run_path(ws: Workspace, run_id: str) -> Path:
    return ws.path / "runs" / run_id


def read_meta(ws: Workspace, run_id: str) -> dict[str, Any] | None:
    path = run_path(ws, run_id) / META_FILE
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data


def write_meta(ws: Workspace, run_id: str, **fields: Any) -> dict[str, Any]:
    meta = read_meta(ws, run_id) or {"run_id": run_id, "project": ws.path.name, "created_at": round(time.time(), 3)}
    meta.update(fields)
    meta["updated_at"] = round(time.time(), 3)
    path = run_path(ws, run_id) / META_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def reopen_for_resume(log: TaskLog, guidance: str | None = None) -> Literal["plan", "act"]:
    """Make a stopped run runnable again. A human has intervened, so an escalated task gets a fresh attempt budget;
    tasks that were blocked behind it become pending again. With a failure to learn from (or guidance), the planner
    goes first; an interrupted run with nothing failed goes straight back to work."""
    problems: list[str] = []
    for task in log.tasks:
        if task.status == "in_progress":
            task.status = "pending"
        elif task.status == "escalated":
            problems.append(f"role: {task.role}\nobjective: {task.objective}\nreason: {task.reason}")
            task.status, task.attempt, task.reasons = "fail", 0, []
        elif task.status == "blocked":
            task.status, task.reason = "pending", ""
    failure = log.last_failure or ("\n\n".join(problems) if problems else None)
    if guidance:
        failure = (failure + "\n\n" if failure else "A person asked to continue this run.\n\n") + f"Guidance from the person:\n{guidance}"
    log.last_failure = failure
    return "plan" if failure else "act"


async def run_graph(state: OrchestratorState) -> OrchestratorState:
    """Run the graph to its end. Never raises for a failed run; always leaves `run_finished` in the event log."""
    ws, run_id = state["workspace"], state["run_id"]
    events: EventLog | None = state.get("events")
    write_meta(ws, run_id, status="running", request=state["request"])
    result: Any = state
    try:
        result = await build_graph().ainvoke(state, {"recursion_limit": RECURSION_LIMIT})
    except asyncio.CancelledError:
        if events is not None and events.last_type != "run_finished":
            events.emit("run_finished", status="stopped", reason="cancelled", message="The run was cancelled.")
        write_meta(ws, run_id, status="stopped", reason="cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 (the run's end must always be recorded)
        message = f"{type(exc).__name__}: {exc}"[:400]
        if events is not None:
            events.emit("run_finished", status="error", reason="error", message=message)
        write_meta(ws, run_id, status="error", reason=message)
        return result
    write_meta(ws, run_id, status=result.get("status", "escalated"), reason=result.get("end_reason"))
    return result
