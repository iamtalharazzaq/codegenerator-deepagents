"""Thin helpers over codewright's Workspace for per-run artifact files.

These wrap `agent.tools.workspace.Workspace` to read/write files under
`workspace.path / "runs" / <run_id> / <filename>` (e.g. design.md,
test-report.md produced during an orchestrator run).
"""

from pathlib import Path

from agent.tools.workspace import Workspace


def run_dir(workspace: Workspace, run_id: str) -> Path:
    """Return the directory for a run's artifacts, creating it if missing."""
    path = workspace.path / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_artifact(workspace: Workspace, run_id: str, filename: str, content: str) -> Path:
    """Write `content` to `filename` under the run's artifact directory."""
    path = run_dir(workspace, run_id) / filename
    path.write_text(content)
    return path


def read_artifact(workspace: Workspace, run_id: str, filename: str) -> str:
    """Read `filename` from the run's artifact directory.

    Raises FileNotFoundError if the artifact does not exist.
    """
    path = run_dir(workspace, run_id) / filename
    return path.read_text()
