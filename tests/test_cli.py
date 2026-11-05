from pathlib import Path
from typing import Any

from click.testing import CliRunner
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from orchestrator.cli import cli


class ScriptedModel(GenericFakeChatModel):
    """`GenericFakeChatModel` raises on `bind_tools`, which `create_deep_agent` always calls.
    Same minimal subclass as `tests/test_graph.py` / `tests/test_role_runner.py`."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def test_resume_with_missing_run_id_fails_clearly(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["resume", "--project", "p1", "--workspaces-root", str(tmp_path), "--run-id", "doesnotexist"])
    assert result.exit_code == 1
    assert "doesnotexist" in result.output
    assert "Traceback" not in result.output
    # A missing run must leave the filesystem untouched -- no stray runs/<run_id>/ directory.
    assert not (tmp_path / "p1" / "runs" / "doesnotexist").exists()


def test_run_exits_nonzero_when_the_graph_escalates(tmp_path: Path, monkeypatch):
    fail = AIMessage(content="---\nstatus: fail\nreason: broken\n---")
    model = ScriptedModel(messages=iter([
        AIMessage(content='```json\n[{"role": "qa_engineer", "objective": "fix", "inputs": [], "done_condition": "passes"}]\n```'),
        fail,
        AIMessage(content='```json\n[{"role": "qa_engineer", "objective": "fix", "inputs": [], "done_condition": "passes"}]\n```'),
        fail,
    ]))
    monkeypatch.setattr("orchestrator.cli.build_model", lambda: model)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--project", "p1", "--workspaces-root", str(tmp_path), "do it"])
    assert result.exit_code == 1
    assert "escalat" in result.output.lower()
