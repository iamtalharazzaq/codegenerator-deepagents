from pathlib import Path
from typing import Any

from click.testing import CliRunner
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from test_team import PASS, calls, delegate, tc

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


def run_cli(tmp_path: Path, monkeypatch, script: list, *args: str):
    monkeypatch.setattr("orchestrator.cli.build_model", lambda: ScriptedModel(messages=iter(script)))
    return CliRunner().invoke(cli, ["run", "--project", "p1", "--workspaces-root", str(tmp_path), *args, "do it"])


def test_run_exits_nonzero_when_the_project_manager_cannot_finish(tmp_path: Path, monkeypatch):
    # it replies in words twice (the second time after the nudge to delegate) and never gives a final status block
    result = run_cli(tmp_path, monkeypatch, [AIMessage(content="I think we are done."), AIMessage(content="Really done.")])
    assert result.exit_code == 1
    assert "escalated" in result.output.lower()


def test_run_exits_zero_when_the_work_passed_and_prints_the_events(tmp_path: Path, monkeypatch):
    script = [
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: a/x.py", "status": "in_progress"}]})),
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "x = 1\n"})),
        AIMessage(content=PASS),
        AIMessage(content="Built.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    result = run_cli(tmp_path, monkeypatch, script)
    assert result.exit_code == 0, result.output
    assert "to-do:" in result.output and "start  backend_developer" in result.output and "Run passed" in result.output


def test_the_plan_prompt_lists_the_to_do_items_and_a_no_with_a_note_sends_the_plan_back(tmp_path: Path, monkeypatch):
    script = [
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: a/x.py", "status": "pending"}]})),
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"),  # held for approval, then sent back
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: a/x.py and tests", "status": "pending"}]})),
        delegate("backend-developer", "Create a/x.py and a test.\nWRITES: a/**", "k2"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "x = 1\n"})),
        AIMessage(content=PASS),
        AIMessage(content="Built.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    monkeypatch.setattr("orchestrator.cli.build_model", lambda: ScriptedModel(messages=iter(script)))
    result = CliRunner().invoke(
        cli, ["run", "--project", "p1", "--workspaces-root", str(tmp_path), "--approve-plan", "do it"], input="n\nadd a test\ny\n"
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Approve?") == 2 and "[pending] Backend Developer: a/x.py and tests" in result.output
