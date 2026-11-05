"""Non-interactive CLI wiring the orchestration graph (Task 8) to persistence (Task 3) and a workspace
(codewright's `Workspace`).

`run` starts a fresh run (new `run_id`), runs the graph to completion, and exits `0` only if every task
in the final task log is `"pass"` (anything else -- a `fail` left open, or an `escalated` task -- exits
`1`). `resume` loads a previously saved `task_log.json` for a given `run_id` and continues the graph from
there; a missing or malformed task log is reported clearly and exits `1` without running anything.

Both commands build a fresh `model`, `Workspace` and `SandboxClient` themselves -- only
`request`/`run_id`/`task_log` ever come from a saved file, so a resumed run always talks to a live
model and sandbox instead of a stale, serialized one.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import click
from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace
from langchain_core.language_models import BaseChatModel

from orchestrator.config import RunConfig
from orchestrator.events import Event, EventLog
from orchestrator.graph import OrchestratorState
from orchestrator.runner import (
    prepare_workspace,
    reopen_for_resume,
    run_graph,
    run_path,
    write_meta,
)
from orchestrator.task import TaskLog, load_task_log

TASK_LOG_FILE = "task_log.json"


def build_model() -> BaseChatModel:
    """The real chat model, built from codewright's own LLM config: `config/models.yaml` plus the same
    `LLM_REMOTE_GPU_URL` / `LLM_LOCAL_CPU_URL` environment overrides `apps/api`'s Settings reads (see
    `codewright/apps/api/src/codewright_api/settings.py::Settings.load_models`). `LLM_PROFILE` picks the
    profile (`remote_gpu` / `local_cpu`); unset, it falls back to the yaml's `default_profile`, same as
    the rest of codewright.
    """
    import agent as _codewright_agent  # local import: only needed on this (untested) real-model path
    from agent.llm.client import LLMClient
    from agent.llm.config import ModelsConfig, ProfileOverride
    from agent.llm.langchain_model import chat_model

    codewright_root = Path(_codewright_agent.__file__).resolve().parents[1]
    config_path = Path(os.environ.get("MODELS_CONFIG", str(codewright_root / "config" / "models.yaml")))
    config = ModelsConfig.from_yaml(config_path)

    overrides: dict[str, ProfileOverride] = {}
    if remote_url := os.environ.get("LLM_REMOTE_GPU_URL"):
        overrides["remote_gpu"] = ProfileOverride(base_url=remote_url)
    if local_url := os.environ.get("LLM_LOCAL_CPU_URL"):
        overrides["local_cpu"] = ProfileOverride(base_url=local_url)
    if overrides:
        config = config.with_overrides(overrides)  # type: ignore[arg-type]

    profile_name = os.environ.get("LLM_PROFILE", config.default_profile)
    client = LLMClient(profile_name, config.profiles[profile_name])  # type: ignore[arg-type]
    return chat_model(client)


def _report(task_log: TaskLog) -> tuple[bool, str]:
    """Final status lines for every task, plus whether the run as a whole succeeded (every task `pass`)."""
    lines = [f"- {t.role} [{t.id}]: {t.status}" for t in task_log.tasks if t.status != "superseded"]
    all_pass = bool(task_log.tasks) and all(t.status in ("pass", "superseded") for t in task_log.tasks)
    if any(t.status == "escalated" for t in task_log.tasks):
        lines.append("Run escalated: a task failed and was not resolved within its retry budget.")
    elif not all_pass:
        lines.append("Run ended with unresolved tasks.")
    return all_pass, "\n".join(lines)


def _print_event(event: Event) -> None:
    """One line per event, so the terminal shows the plan, each dispatch and each replan as they happen."""
    kind = event["type"]
    task: dict = event.get("task") or {}
    line: str | None = None
    if kind == "plan_ready":
        line = f"{'replan' if event.get('replan') else 'plan'}: {len(event['tasks'])} task(s). {event.get('reason', '')}".strip()
    elif kind == "task_started":
        line = f"start  {task['role']} (try {task['attempt']}): {task['objective']}"
    elif kind == "tool_call":
        line = f"  tool {event['role']}: {event['tool']} {event.get('summary', '')}".rstrip()
    elif kind == "task_finished":
        line = f"{event['verdict']:5}  {task['role']}: {task['reason']}"
    elif kind == "guardrail_hit":
        line = f"guardrail {event['kind']}: {event.get('reason', '')}"
    elif kind == "plan_invalid":
        line = f"plan rejected: {event['error']}"
    elif kind == "run_finished":
        line = f"finished: {event['status']} ({event['message']})"
    if line:
        click.echo(line)


def _make_state(
    workspace: Workspace, run_id: str, task_log: TaskLog, config: RunConfig, approve: bool, base: str | None
) -> OrchestratorState:
    events = EventLog(run_path(workspace, run_id) / "events.jsonl", on_emit=_print_event)

    async def ask(payload: dict) -> bool:
        listing = "\n".join(f"  - {t['role']}: {t['objective']}" for t in payload["tasks"])
        return await asyncio.to_thread(click.confirm, f"Plan:\n{listing}\nApprove?", default=True)

    return {
        "request": task_log.request,
        "workspace": workspace,
        "run_id": run_id,
        "model": build_model(),
        "sandbox_client": SandboxClient(),
        "task_log": task_log,
        "last_failure": task_log.last_failure,
        "config": config,
        "events": events,
        "approve": ask if approve else None,
        "base_commit": base,
    }


def _events(state: OrchestratorState) -> EventLog:
    events = state.get("events")
    assert events is not None  # _make_state always sets it
    return events


def _finish(task_log: TaskLog) -> None:
    ok, summary = _report(task_log)
    click.echo(summary)
    sys.exit(0 if ok else 1)


_WORKSPACES = click.option(
    "--workspaces-root",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
    help="Root directory holding project workspaces.",
)
_PROJECT = click.option("--project", required=True, help="Project id (the workspace's name under --workspaces-root).")
_CONCURRENCY = click.option("--concurrency", default=1, show_default=True, help="Tasks to run at once.")
_APPROVE = click.option("--approve-plan", is_flag=True, help="Ask before any agent starts, showing the plan.")


@click.group()
def cli() -> None:
    """Orchestrator CLI: run a request through the role roster, or resume an earlier run."""


@cli.command()
@_PROJECT
@_WORKSPACES
@_CONCURRENCY
@_APPROVE
@click.argument("request")
def run(project: str, workspaces_root: Path, concurrency: int, approve_plan: bool, request: str) -> None:
    """Start a fresh orchestration run for REQUEST."""
    workspace = Workspace(Path(workspaces_root), project)
    run_id = uuid4().hex[:8]
    base = prepare_workspace(workspace, run_id)
    click.echo(f"Starting run {run_id!r} for project {project!r}: {request}")
    config = RunConfig(concurrency=concurrency, plan_approval=approve_plan)
    state = _make_state(workspace, run_id, TaskLog(run_id=run_id, request=request, tasks=[]), config, approve_plan, base)
    _events(state).emit("run_started", run_id=run_id, project=project, request=request)
    write_meta(workspace, run_id, project=project, request=request, status="running")
    result = asyncio.run(run_graph(state))
    _finish(result["task_log"])


@cli.command()
@_PROJECT
@_WORKSPACES
@click.option("--run-id", required=True, help="Run id to resume (as generated by a previous `run`).")
@click.option("--guidance", default=None, help="Tell the planner what to change before it carries on.")
@_CONCURRENCY
def resume(project: str, workspaces_root: Path, run_id: str, guidance: str | None, concurrency: int) -> None:
    """Resume a previously started run from its saved task log."""
    workspace = Workspace(Path(workspaces_root), project)
    workspace.create()
    # Read-only lookup: unlike `run_dir()`, this must not create `runs/<run_id>/` just to check whether
    # it holds a usable task log -- a missing/malformed run should leave the filesystem untouched.
    log_path = workspace.path / "runs" / run_id / TASK_LOG_FILE
    try:
        task_log = load_task_log(log_path)
    except (FileNotFoundError, json.JSONDecodeError) as err:
        click.echo(f"No usable run {run_id!r}: {err}")
        sys.exit(1)

    click.echo(f"Resuming run {run_id!r} for project {project!r}.")
    start_at = reopen_for_resume(task_log, guidance)
    state = _make_state(workspace, run_id, task_log, RunConfig(concurrency=concurrency), False, None)
    state["start_at"] = start_at
    _events(state).emit("run_resumed", run_id=run_id, guidance=guidance or "", start_at=start_at)
    result = asyncio.run(run_graph(state))
    _finish(result["task_log"])


if __name__ == "__main__":
    cli()
