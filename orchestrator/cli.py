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

from orchestrator.graph import OrchestratorState, build_graph
from orchestrator.runs import run_dir
from orchestrator.task import TaskLog, load_task_log, save_task_log

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
    lines = [f"- {t.role} [{t.id}]: {t.status}" for t in task_log.tasks]
    all_pass = bool(task_log.tasks) and all(t.status == "pass" for t in task_log.tasks)
    if any(t.status == "escalated" for t in task_log.tasks):
        lines.append("Run escalated: a task failed and was not resolved within its retry budget.")
    elif not all_pass:
        lines.append("Run ended with unresolved tasks.")
    return all_pass, "\n".join(lines)


async def _advance(state: OrchestratorState, workspace: Workspace, run_id: str) -> TaskLog:
    result = await build_graph().ainvoke(state)
    task_log: TaskLog = result["task_log"]
    save_task_log(task_log, run_dir(workspace, run_id) / TASK_LOG_FILE)
    return task_log


@click.group()
def cli() -> None:
    """Orchestrator CLI: run a request through the role roster, or resume an earlier run."""


@cli.command()
@click.option("--project", required=True, help="Project id (the workspace's name under --workspaces-root).")
@click.option(
    "--workspaces-root",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
    help="Root directory holding project workspaces.",
)
@click.argument("request")
def run(project: str, workspaces_root: Path, request: str) -> None:
    """Start a fresh orchestration run for REQUEST."""
    workspace = Workspace(Path(workspaces_root), project)
    workspace.create()
    run_id = uuid4().hex[:8]
    click.echo(f"Starting run {run_id!r} for project {project!r}: {request}")

    state: OrchestratorState = {
        "request": request,
        "workspace": workspace,
        "run_id": run_id,
        "model": build_model(),
        "sandbox_client": SandboxClient(),
        "task_log": TaskLog(run_id=run_id, request=request, tasks=[]),
        "last_failure": None,
    }
    task_log = asyncio.run(_advance(state, workspace, run_id))
    ok, summary = _report(task_log)
    click.echo(summary)
    sys.exit(0 if ok else 1)


@cli.command()
@click.option("--project", required=True, help="Project id (the workspace's name under --workspaces-root).")
@click.option(
    "--workspaces-root",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
    help="Root directory holding project workspaces.",
)
@click.option("--run-id", required=True, help="Run id to resume (as generated by a previous `run`).")
def resume(project: str, workspaces_root: Path, run_id: str) -> None:
    """Resume a previously started run from its saved task log."""
    workspace = Workspace(Path(workspaces_root), project)
    workspace.create()
    log_path = run_dir(workspace, run_id) / TASK_LOG_FILE
    try:
        task_log = load_task_log(log_path)
    except (FileNotFoundError, json.JSONDecodeError) as err:
        click.echo(f"No usable run {run_id!r}: {err}")
        sys.exit(1)

    click.echo(f"Resuming run {run_id!r} for project {project!r}.")
    state: OrchestratorState = {
        "request": task_log.request,
        "workspace": workspace,
        "run_id": run_id,
        "model": build_model(),
        "sandbox_client": SandboxClient(),
        "task_log": task_log,
        "last_failure": None,
    }
    task_log = asyncio.run(_advance(state, workspace, run_id))
    ok, summary = _report(task_log)
    click.echo(summary)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    cli()
