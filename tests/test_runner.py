import json
from pathlib import Path

from agent.tools.workspace import Workspace, git
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from orchestrator.events import EventLog
from orchestrator.runner import (
    prepare_workspace,
    read_meta,
    resume_note,
    run_graph,
    write_meta,
)
from orchestrator.task import Task, TaskLog


class EmptyModel(GenericFakeChatModel):
    """Raises as soon as the planner asks it anything (its script is empty)."""

    def bind_tools(self, tools, **kwargs):
        return self


def mk(status: str, **kw) -> Task:
    return Task(id=kw.pop("id", "t1"), role="qa_engineer", objective="o", status=status, **kw)


def test_prepare_workspace_creates_a_repo_and_a_run_branch(tmp_path: Path):
    ws = Workspace(tmp_path, "p1")
    base = prepare_workspace(ws, "r1")
    assert base and git(ws.work, "branch", "--show-current") == "run/r1"


def test_meta_round_trips_and_merges(tmp_path: Path):
    ws = Workspace(tmp_path, "p1")
    ws.create()
    assert read_meta(ws, "r1") is None
    write_meta(ws, "r1", status="running", request="x")
    write_meta(ws, "r1", status="passed")
    meta = read_meta(ws, "r1")
    assert meta["status"] == "passed" and meta["request"] == "x" and meta["project"] == "p1"


def test_resume_note_tells_the_project_manager_what_passed_and_what_failed():
    log = TaskLog("r1", "x", [mk("pass", id="a", reason="done"), mk("fail", id="b", reason="tests red"),
                              mk("in_progress", id="c")])
    note = resume_note(log, "use pytest -x", "A task failed its last attempt.")
    assert "passed: qa_engineer: o" in note and "FAILED: qa_engineer: o | reason: tests red" in note
    assert "interrupted before it finished" in note  # a delegation cut off mid-run counts as failed
    assert "A task failed its last attempt." in note and "Guidance from the person: use pytest -x" in note
    assert log.tasks[2].status == "fail"


def test_resume_note_without_history_or_guidance_is_still_a_clear_instruction():
    note = resume_note(TaskLog("r1", "x", []))
    assert "stopped earlier" in note and "final status block" in note and "Guidance" not in note


async def test_an_unexpected_crash_still_ends_the_run_with_an_event(tmp_path: Path):
    ws = Workspace(tmp_path, "p1")
    ws.create()
    events = EventLog(tmp_path / "e.jsonl")
    # The model has nothing to say, so the graph raises on its first call.
    state = {"request": "x", "workspace": ws, "run_id": "r1", "model": EmptyModel(messages=iter([])),
             "task_log": TaskLog("r1", "x", []), "events": events}
    await run_graph(state)  # must not raise
    last = events.since(0)[-1]
    assert last["type"] == "run_finished" and last["status"] == "error"
    assert read_meta(ws, "r1")["status"] == "error"
    assert json.loads((tmp_path / "e.jsonl").read_text().splitlines()[-1])["status"] == "error"


def test_project_and_zip_names_are_short_readable_and_the_zip_has_no_run_id():
    from orchestrator.runner import new_project_name, zip_filename

    name = new_project_name("Please, can you create a forgot-password flow for the shop with an email link?", "c5c38465")
    assert name == "create-a-forgot-password-flow-c5c38465"  # whole words, filler dropped, id keeps the folder unique
    assert zip_filename(name, "c5c38465") == "create-a-forgot-password-flow.zip"
    assert zip_filename(name, "c5c38465", partial=True) == "create-a-forgot-password-flow-partial.zip"
    assert zip_filename("my-own-project", "c5c38465") == "my-own-project.zip"  # a project the person named is left alone
    assert new_project_name("???", "ab12cd34") == "run-ab12cd34"
    assert new_project_name("Build a calculator with a", "ab12cd34") == "build-a-calculator-ab12cd34"


def test_a_new_project_name_always_fits_the_name_rule_of_the_server():
    """A request whose slug filled all 32 characters made a 41-character name, which the server refused (HTTP 400)."""
    import re

    from orchestrator.runner import new_project_name

    for request in ("A tool that converts km to miles", "a b c d e f g h i j k l m n o p q r s t u v w x y z", "x" * 100):
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,40}", new_project_name(request, "ab12cd34")), request
