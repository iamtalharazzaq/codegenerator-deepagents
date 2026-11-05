from pathlib import Path

import pytest
from agent.tools.workspace import Workspace

from orchestrator.runs import read_artifact, run_dir, write_artifact


def test_write_then_read_artifact(tmp_path: Path):
    ws = Workspace(tmp_path, "proj1")
    ws.create()
    write_artifact(ws, "run1", "design.md", "# Design\n...")
    assert read_artifact(ws, "run1", "design.md") == "# Design\n..."
    assert run_dir(ws, "run1") == tmp_path / "proj1" / "runs" / "run1"


def test_read_missing_artifact_raises(tmp_path: Path):
    ws = Workspace(tmp_path, "proj1")
    ws.create()
    with pytest.raises(FileNotFoundError):
        read_artifact(ws, "run1", "nope.md")
