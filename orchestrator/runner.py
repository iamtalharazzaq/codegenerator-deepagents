"""Starting, resuming and running a run: the pieces the CLI and the web service share.

- `prepare_workspace`: a git repo in `work/` and a `run/<run_id>` branch; returns the base commit for the report.
- `meta.json` per run: what the run list shows (status, request, project), updated as the run moves.
- `resume_fields`: how a stopped run carries on. A run cut off mid-way (`interrupted`) continues its checkpointed
  Project Manager conversation exactly where it stopped, unless the person gives guidance; any other stopped run starts
  a fresh conversation that begins with `resume_note` (what already happened).
- `run_graph`: runs the team, and makes sure a run *always* ends
  with a `run_finished` event, even when something unexpected raises.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from agent.tools.workspace import Workspace, git

from orchestrator.events import EventLog
from orchestrator.task import TaskLog, mark_interrupted
from orchestrator.team import OrchestratorState, run_team

META_FILE = "meta.json"
DANGLING_WORDS = {"a", "an", "the", "with", "for", "and", "or", "to", "of", "in", "on", "at", "by", "as", "that", "which", "from", "into"}
FILLER_RE = re.compile(r"^(?:please|kindly|hey|hi|hello|can you|could you|would you|i (?:want|need|would like) (?:you )?to|i'd like (?:you )?to|let's|lets)\b[\s,:;-]*")


def new_project_name(request: str, run_id: str) -> str:
    """A fresh project for one request, e.g. `calculator-in-python-c5c38465`. Every run starts from an empty folder
    unless the person picks an existing project, so a zip holds what this request produced and nothing older."""
    text = request.lower().strip()
    while (stripped := FILLER_RE.sub("", text).strip()) != text:  # drop "please", "can you"... like the UI's heading does
        text = stripped
    slug = ""
    for word in re.findall(r"[a-z0-9]+", text):  # whole words only, so the name never ends mid-word
        if len(slug) + len(word) + 1 > 31:  # name = slug + "-" + 8-char run id must stay within 40 characters
            break
        slug = f"{slug}-{word}" if slug else word
    while "-" in slug and slug.rsplit("-", 1)[1] in DANGLING_WORDS:  # and never on "a", "with", "the"...
        slug = slug.rsplit("-", 1)[0]
    return f"{slug or 'run'}-{run_id}"


def zip_filename(project: str, run_id: str, partial: bool = False) -> str:
    """The name a downloaded zip gets: the project's name without the run id that keeps its folder unique."""
    name = project.removesuffix(f"-{run_id}") or "project"
    return f"{name}{'-partial' if partial else ''}.zip"


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


def resume_note(log: TaskLog, guidance: str | None = None, previous_reason: str | None = None) -> str:
    """Tell the Project Manager what already happened in a stopped run, so it carries on instead of starting over.
    A delegation that was still running when the run was cut off counts as failed."""
    lines = []
    mark_interrupted(log)
    for task in log.tasks:
        done = "passed" if task.status == "pass" else "FAILED"
        extra = f" | reason: {task.reason}" if task.status != "pass" and task.reason else ""
        lines.append(f"- {done}: {task.role}: {task.objective}{extra}")
    note = ["This run was stopped earlier."]
    if previous_reason:
        note.append(f"How it ended: {previous_reason}.")
    if lines:
        note += ["Work so far (do not redo what passed):", *lines]
    if guidance:
        note += ["", f"Guidance from the person: {guidance}"]
    note += ["", "Carry on from here: fix or redo only what is needed, then finish with the final status block."]
    return "\n".join(note)


def resume_fields(ws: Workspace, run_id: str, log: TaskLog, guidance: str | None = None) -> dict[str, Any]:
    """The state keys that make a run carry on: `thread_id` (and `resume_note` when a fresh conversation is needed)."""
    meta = read_meta(ws, run_id) or {}
    if meta.get("status") == "interrupted" and meta.get("thread_id") and not guidance:
        return {"thread_id": meta["thread_id"]}
    return {"thread_id": f"{run_id}-{uuid.uuid4().hex[:6]}", "resume_note": resume_note(log, guidance, meta.get("reason"))}


async def run_graph(state: OrchestratorState) -> OrchestratorState:
    """Run the team to its end. Never raises for a failed run; always leaves `run_finished` in the event log."""
    ws, run_id = state["workspace"], state["run_id"]
    events: EventLog | None = state.get("events")
    write_meta(ws, run_id, status="running", request=state["request"], thread_id=state.setdefault("thread_id", run_id))
    result: Any = state
    try:
        result = await run_team(state)
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
