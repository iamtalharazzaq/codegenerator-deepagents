"""The team (Project Manager deep agent + specialists as deepagents sub-agents), run for real with scripted models."""

import asyncio
import zipfile
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from agent.tools.workspace import Workspace, git
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.team import (
    REASONS,
    objective_of,
    parse_writes,
    resolve_role,
    run_team,
)

PASS = "Did it.\n---\nstatus: pass\nreason: ok\n---"
FAIL = "Could not.\n---\nstatus: fail\nreason: broken\n---"


class ScriptedModel(GenericFakeChatModel):
    """One scripted stream of replies shared by the Project Manager and the sub-agents (they run in turn)."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def tc(name: str, args: dict, id_: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def calls(*items: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(items))


def delegate(role: str, description: str, id_: str = "k1") -> AIMessage:
    return calls(tc("task", {"description": description, "subagent_type": role}, id_))


async def run(tmp_path: Path, script: list, *, cfg: RunConfig | None = None, approve=None, review=None, note=None, model=None, git_repo=True):
    ws = Workspace(tmp_path, "p1")
    ws.create()
    if git_repo:
        ws.init_git()
    events = EventLog(ws.path / "runs" / "r1" / "events.jsonl")
    from orchestrator.task import TaskLog

    state: dict[str, Any] = {
        "request": "build it", "workspace": ws, "run_id": "r1", "model": model or ScriptedModel(messages=iter(script)),
        "task_log": TaskLog("r1", "build it", []), "events": events, "config": cfg or RunConfig(), "approve": approve, "review": review,
        "base_commit": git(ws.work, "rev-parse", "HEAD") if git_repo else None, "resume_note": note,
    }
    result = await run_team(state)  # type: ignore[arg-type]
    return ws, events, result


def types(events: EventLog) -> list[str]:
    return [e["type"] for e in events.since(0)]


def hits(events: EventLog) -> list[dict]:
    return [e for e in events.since(0) if e["type"] == "guardrail_hit"]


# ---------------------------------------------------------------- the basics


def test_helpers_read_the_delegation_text():
    assert parse_writes("Do it\nWRITES: backend/**, `docs/api.md` tests/") == ("backend/**", "docs/api.md", "tests/")
    assert parse_writes("Do it") == () and parse_writes("x\nWRITES: none") == ()
    assert objective_of("\nBuild the API\nmore\nWRITES: a/**") == "Build the API"
    assert resolve_role("backend-developer") == "backend_developer" and resolve_role("Backend_Developer") == "backend_developer"
    assert resolve_role("project-manager") is None and resolve_role("general-purpose") is None and resolve_role("ceo") is None


async def test_the_project_manager_delegates_to_a_real_subagent_and_everything_is_recorded(tmp_path):
    script = [
        calls(tc("write_todos", {"todos": [{"content": "Backend: add a/x.py", "status": "in_progress"}]})),
        delegate("backend-developer", "Create a/x.py with one function.\nWRITES: a/**"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "def f(): return 1\n"})),
        AIMessage(content="Wrote a/x.py.\n---\nstatus: pass\nreason: file written\n---"),
        AIMessage(content="The backend is done.\n---\nstatus: pass\nreason: all tasks passed\n---"),
    ]
    ws, events, result = await run(tmp_path, script)
    assert result["status"] == "passed" and result["end_reason"] == "all_passed"
    assert (ws.work / "a" / "x.py").read_text() == "def f(): return 1\n"
    order = types(events)
    assert order[:2] == ["plan_started", "todos_updated"]
    assert order.index("task_started") < order.index("tool_call") < order.index("task_finished") < order.index("run_finished")
    started = next(e for e in events.since(0) if e["type"] == "task_started")["task"]
    assert (started["role"], started["status"], started["writes"]) == ("backend_developer", "in_progress", ["a/**"])
    finished = next(e for e in events.since(0) if e["type"] == "task_finished")
    assert finished["verdict"] == "pass" and finished["task"]["reason"] == "file written"
    tool = next(e for e in events.since(0) if e["type"] == "tool_call")
    assert (tool["tool"], tool["task_id"], tool["role"]) == ("write_file", started["id"], "backend_developer")
    todos = next(e for e in events.since(0) if e["type"] == "todos_updated")["todos"]
    assert todos == [{"content": "Backend: add a/x.py", "status": "in_progress"}]
    # the delegation is committed under its own role, and the report and zip exist
    assert "backend_developer: Create a/x.py" in git(ws.work, "log", "--format=%s")
    runs = ws.path / "runs" / "r1"
    assert "Run r1: passed" in (runs / "report.md").read_text() and "The backend is done." in (runs / "report.md").read_text()
    assert "a/x.py" in zipfile.ZipFile(runs / "delivery.zip").namelist()
    assert (runs / f"{started['id']}.md").exists() and (runs / f"{started['id']}.attempt1.md").exists()


async def test_the_project_manager_cannot_write_files_itself(tmp_path):
    script = [
        calls(tc("write_file", {"file_path": "/hack.py", "content": "x"})),
        AIMessage(content="Gave up.\n---\nstatus: fail\nreason: nothing delegated\n---"),
    ]
    ws, _, result = await run(tmp_path, script, cfg=RunConfig(max_nudges=0))
    assert not (ws.work / "hack.py").exists() and result["status"] == "escalated"


# ---------------------------------------------------------------- guardrails on the specialists


async def test_writes_outside_the_declared_paths_are_blocked_and_repeated_attempts_stop_the_task(tmp_path):
    script = [
        delegate("backend-developer", "Make a thing.\nWRITES: a/**"),
        calls(tc("write_file", {"file_path": "/b/one.py", "content": "x"}, "w1")),
        calls(tc("write_file", {"file_path": "/b/two.py", "content": "x"}, "w2")),
        calls(tc("write_file", {"file_path": "/b/three.py", "content": "x"}, "w3")),
        calls(tc("write_file", {"file_path": "/b/four.py", "content": "x"}, "w4")),
        AIMessage(content="I could not finish.\n---\nstatus: fail\nreason: the task was stopped\n---"),
    ]
    ws, events, result = await run(tmp_path, script)
    assert not (ws.work / "b").exists()
    assert [h["kind"] for h in hits(events)] == ["write_blocked", "write_blocked", "write_blocked", "agent_stuck"]
    task = result["task_log"].tasks[0]
    assert task.status == "fail" and "blocked path 3 times" in task.reason
    assert result["status"] == "escalated" and result["end_reason"] == "pm_failed"


async def test_the_git_folder_cannot_be_listed_by_a_specialist(tmp_path):
    script = [
        delegate("backend-developer", "Look around.\nWRITES: a/**"),
        calls(tc("ls", {"path": "/.git"}, "l1")),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    _, events, _ = await run(tmp_path, script)
    assert [(h["kind"], h["reason"]) for h in hits(events)] == [("path_blocked", "the .git folder is not available")]


async def test_a_specialist_repeating_the_same_call_is_stopped(tmp_path):
    same = [calls(tc("read_file", {"file_path": "/nope.txt"}, f"r{i}")) for i in range(8)]
    script = [delegate("backend-developer", "Read.\nWRITES: a/**"), *same, AIMessage(content=FAIL)]
    _, events, result = await run(tmp_path, script)
    assert any(h["kind"] == "agent_stuck" and "repeated the same read_file call 4 times" in h["reason"] for h in hits(events))
    assert result["task_log"].tasks[0].status == "fail"


async def test_a_task_over_its_time_limit_fails_with_a_guardrail_event(tmp_path):
    class Slow(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(m, HumanMessage) and "Slow job" in str(m.content) for m in messages):
                await asyncio.sleep(2)
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    script = [delegate("backend-developer", "Slow job.\nWRITES: a/**"), AIMessage(content="never"), AIMessage(content=FAIL)]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(task_timeout_s=0.1), model=Slow(messages=iter(script)))
    assert any(h["kind"] == "task_timeout" for h in hits(events))
    assert result["task_log"].tasks[0].status == "fail" and "timed out" in result["task_log"].tasks[0].reason


async def test_a_specialist_whose_model_call_raises_is_a_failed_task_not_a_crashed_run(tmp_path):
    class Boom(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(m, HumanMessage) and "Explode" in str(m.content) for m in messages):
                raise RuntimeError("model unavailable")
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    script = [delegate("backend-developer", "Explode.\nWRITES: a/**"), AIMessage(content=FAIL)]
    _, _, result = await run(tmp_path, script, model=Boom(messages=iter(script)))
    assert "RuntimeError: model unavailable" in result["task_log"].tasks[0].reason
    assert result["status"] == "escalated"


# ---------------------------------------------------------------- the roster


async def test_a_specialist_outside_the_roster_is_refused_and_so_is_general_purpose(tmp_path):
    seen: list[str] = []

    class Spy(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.extend(str(m.content) for m in messages if isinstance(m, ToolMessage))
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    script = [
        delegate("hacker", "Do crimes.", "k1"),
        delegate("general-purpose", "Write /loose.txt.", "k2"),
        AIMessage(content="Nothing done.\n---\nstatus: fail\nreason: nothing passed\n---"),
    ]
    ws, events, result = await run(tmp_path, script, cfg=RunConfig(max_nudges=0), model=Spy(messages=iter(script)))
    assert not (ws.work / "loose.txt").exists() and "task_started" not in types(events) and result["task_log"].tasks == []
    refusals = {m for m in seen if "Unknown sub-agent" in m}
    assert len(refusals) == 2 and all("backend-developer" in m for m in refusals)  # each names the real roster


async def test_the_delegation_limit_stops_further_work(tmp_path):
    script = [
        delegate("backend-developer", "First.\nWRITES: a/**", "k1"),
        AIMessage(content=PASS),
        delegate("backend-developer", "Second.\nWRITES: b/**", "k2"),
        AIMessage(content="Stopped at the limit.\n---\nstatus: fail\nreason: delegation limit\n---"),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(max_total_dispatches=1))
    assert [h["kind"] for h in hits(events)] == ["dispatch_cap"]
    assert len(result["task_log"].tasks) == 1


# ---------------------------------------------------------------- approval


async def test_the_first_delegation_waits_for_approval_and_only_asks_once(tmp_path):
    asked = []

    async def approve(payload):
        asked.append(payload["todos"])
        return {"approved": True}

    script = [
        calls(tc("write_todos", {"todos": [{"content": "A", "status": "pending"}]})),
        delegate("backend-developer", "One.", "k1"),
        AIMessage(content=PASS),
        delegate("backend-developer", "Two.", "k2"),
        AIMessage(content=PASS),
        AIMessage(content=PASS),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True), approve=approve)
    assert asked == [[{"content": "A", "status": "pending"}]] and result["status"] == "passed"
    order = types(events)
    assert order.index("plan_approval_requested") < order.index("plan_approved") < order.index("task_started")


async def test_a_rejected_plan_delegates_nothing_and_the_run_is_stopped(tmp_path):
    async def reject(payload):
        return {"approved": False}

    script = [
        delegate("backend-developer", "One."),
        AIMessage(content="Rejected.\n---\nstatus: fail\nreason: plan rejected\n---"),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True), approve=reject)
    assert (result["status"], result["end_reason"]) == ("stopped", "plan_rejected")
    assert "task_started" not in types(events) and result["task_log"].tasks == []


# ---------------------------------------------------------------- how a run ends


@pytest.mark.parametrize(
    ("final", "status", "reason"),
    [
        ("I think we are done.", "escalated", "no_final_status"),
        ("Could not.\n---\nstatus: fail\nreason: broken\n---", "escalated", "pm_failed"),
        ("All good.\n---\nstatus: pass\nreason: fine\n---", "escalated", "no_task_passed"),  # nothing was delegated
    ],
)
async def test_the_final_status_rules(tmp_path, final, status, reason):
    _, events, result = await run(tmp_path, [AIMessage(content=final)], cfg=RunConfig(max_nudges=0))
    assert (result["status"], result["end_reason"]) == (status, reason)
    assert types(events)[-1] == "run_finished" and not (tmp_path / "p1" / "runs" / "r1" / "delivery.zip").exists()


async def test_a_secret_in_the_code_blocks_the_zip_but_not_the_report(tmp_path):
    script = [
        delegate("backend-developer", "Config.\nWRITES: cfg/**"),
        calls(tc("write_file", {"file_path": "/cfg/k.py", "content": 'KEY = "AKIAABCDEFGHIJKLMNOP"\n'})),
        AIMessage(content=PASS),
        AIMessage(content=PASS),
    ]
    ws, events, result = await run(tmp_path, script)
    runs = ws.path / "runs" / "r1"
    assert result["status"] == "passed" and not (runs / "delivery.zip").exists()
    assert "not built" in (runs / "report.md").read_text() and "AKIA" not in (runs / "report.md").read_text()
    assert [h["kind"] for h in hits(events)] == ["secret_scan"]


async def test_the_run_timeout_ends_the_run_with_a_report(tmp_path):
    class Hang(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            await asyncio.sleep(5)
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    _, _, result = await run(tmp_path, [AIMessage(content=PASS)], cfg=RunConfig(run_timeout_s=0.1), model=Hang(messages=iter([])))
    assert (result["status"], result["end_reason"]) == ("escalated", "run_timeout")
    assert (tmp_path / "p1" / "runs" / "r1" / "report.md").exists()


async def test_a_resumed_run_tells_the_project_manager_what_already_happened(tmp_path):
    seen: list[str] = []

    class Spy(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(str(next(m for m in messages if isinstance(m, HumanMessage)).content))
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    note = "This run was stopped earlier.\n- passed: backend_developer: Build API\nGuidance from the person: skip the UI"
    await run(tmp_path, [AIMessage(content=PASS)], note=note, cfg=RunConfig(max_nudges=0), model=Spy(messages=iter([AIMessage(content=PASS)])))
    assert "Request:\nbuild it" in seen[0] and "passed: backend_developer: Build API" in seen[0] and "skip the UI" in seen[0]


# ---------------------------------------------------------------- parallel delegation


class RoleModel(BaseChatModel):
    """Plays the Project Manager and the specialists by reading the system prompt, so parallel runs are deterministic."""

    active: int = 0
    max_active: int = 0

    @property
    def _llm_type(self) -> str:
        return "role-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RoleModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # pragma: no cover
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = str(next(m.content for m in messages if isinstance(m, SystemMessage)))
        human = str(next(m.content for m in messages if isinstance(m, HumanMessage)).content if False else next(m.content for m in messages if isinstance(m, HumanMessage)))
        wrote = any(isinstance(m, ToolMessage) for m in messages)
        if "You are the Project Manager" in system:
            if wrote:
                msg = AIMessage(content="Both done.\n---\nstatus: pass\nreason: ok\n---")
            else:
                msg = AIMessage(content="", tool_calls=[
                    tc("task", {"description": "Make a.\nWRITES: a/**", "subagent_type": "backend-developer"}, "k1"),
                    tc("task", {"description": "Make b.\nWRITES: b/**", "subagent_type": "frontend-developer"}, "k2"),
                ])
        else:
            folder = "a" if "Make a" in human else "b"
            if wrote:
                msg = AIMessage(content=f"Made {folder}.\n---\nstatus: pass\nreason: ok\n---")
            else:
                msg = AIMessage(content="", tool_calls=[tc("write_file", {"file_path": f"/{folder}/f.py", "content": folder}, f"w{folder}")])
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


async def test_parallel_delegations_run_together_and_are_committed_separately(tmp_path):
    model = RoleModel()
    ws, events, result = await run(tmp_path, [], cfg=RunConfig(concurrency=2), model=model)
    assert result["status"] == "passed" and model.max_active == 2
    base_subjects = git(ws.work, "log", "--reverse", "--format=@@%s", "--name-only").split("@@")[2:]
    committed = sorted((blk.splitlines()[0].split(":")[0], [x for x in blk.splitlines()[1:] if x.strip()]) for blk in base_subjects if "backend" in blk or "frontend" in blk)
    assert committed == [("backend_developer", ["a/f.py"]), ("frontend_developer", ["b/f.py"])]
    starts = [i for i, t in enumerate(types(events)) if t == "task_started"]
    finishes = [i for i, t in enumerate(types(events)) if t == "task_finished"]
    assert max(starts) < min(finishes)  # both started before either finished


async def test_concurrency_one_runs_delegations_one_at_a_time(tmp_path):
    model = RoleModel()
    _, events, result = await run(tmp_path, [], cfg=RunConfig(concurrency=1), model=model)
    assert result["status"] == "passed" and model.max_active == 1
    order = types(events)
    assert order.index("task_finished") < [i for i, t in enumerate(order) if t == "task_started"][1]


async def test_what_the_project_manager_says_alongside_a_tool_call_becomes_a_pm_said_event(tmp_path):
    script = [
        AIMessage(content="I will start with the backend because the UI depends on it.",
                  tool_calls=[tc("task", {"description": "Do it.\nWRITES: a/**", "subagent_type": "backend-developer"}, "k1")]),
        AIMessage(content=PASS),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    _, events, _result = await run(tmp_path, script)
    said = [e["text"] for e in events.since(0) if e["type"] == "pm_said"]
    assert said == ["I will start with the backend because the UI depends on it."]  # once, and not the final reply
    finished = next(e for e in events.since(0) if e["type"] == "run_finished")
    assert finished["summary"] == "Done."  # the final reply without its status block
    assert types(events).index("pm_said") < types(events).index("task_started")


async def test_a_project_manager_that_ends_without_delegating_is_nudged_once_and_then_does_the_work(tmp_path):
    """Seen with the real 9B model: it wrote a to-do list, marked it done, and claimed files it cannot create."""
    script = [
        AIMessage(content="I have created both files.\n---\nstatus: pass\nreason: done\n---"),  # no delegation at all
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content="Now it is really done.\n---\nstatus: pass\nreason: all passed\n---"),
    ]
    ws, events, result = await run(tmp_path, script)
    assert result["status"] == "passed" and (ws.work / "a" / "x.py").exists()
    order = types(events)
    assert order.count("pm_nudged") == 1 and order.index("pm_nudged") < order.index("task_started")


async def test_the_nudge_happens_only_once_and_a_false_claim_still_fails_the_run(tmp_path):
    script = [
        AIMessage(content="Created them.\n---\nstatus: pass\nreason: done\n---"),
        AIMessage(content="Really, they exist.\n---\nstatus: pass\nreason: done\n---"),
    ]
    _, events, result = await run(tmp_path, script)
    assert types(events).count("pm_nudged") == 1
    assert (result["status"], result["end_reason"]) == ("escalated", "no_task_passed")


async def test_no_nudge_when_the_work_was_delegated(tmp_path):
    script = [delegate("backend-developer", "Do it.\nWRITES: a/**"), AIMessage(content=PASS), AIMessage(content=PASS)]
    _, events, _ = await run(tmp_path, script)
    assert "pm_nudged" not in types(events)


# ---------------------------------------------------------------- the final review


def two_step_script() -> list:
    return [
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**", "k1"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content="Built a/x.py.\n---\nstatus: pass\nreason: all passed\n---"),
    ]


async def test_the_zip_is_built_only_after_the_person_accepts(tmp_path):
    asked: list[dict] = []
    zip_path = tmp_path / "p1" / "runs" / "r1" / "delivery.zip"

    async def review(payload):
        asked.append({"zip_existed": zip_path.exists(), **payload})
        return {"accept": True, "changes": ""}

    _ws, events, result = await run(tmp_path, two_step_script(), cfg=RunConfig(final_review=True), review=review)
    assert result["status"] == "passed" and asked == [{"zip_existed": False, "round": 1}] and zip_path.exists()
    requested = next(e for e in events.since(0) if e["type"] == "review_requested")
    assert requested["files"] == ["a/x.py"] and requested["summary"] == "Built a/x.py."  # the status block is not shown
    order = types(events)
    assert order.index("review_requested") < order.index("review_accepted") < order.index("delivery_ready")


async def test_asked_for_changes_the_project_manager_gets_the_note_does_the_work_and_is_reviewed_again(tmp_path):
    seen: list[str] = []

    class Spy(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.extend(str(m.content) for m in messages if isinstance(m, HumanMessage))
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    script = [
        *two_step_script(),
        delegate("backend-developer", "Create b/y.py.\nWRITES: b/**", "k2"),
        calls(tc("write_file", {"file_path": "/b/y.py", "content": "2"}, "w2")),
        AIMessage(content=PASS),
        AIMessage(content="Added b/y.py too.\n---\nstatus: pass\nreason: changed\n---"),
    ]
    decisions = iter([{"accept": False, "changes": "also add b/y.py"}, {"accept": True, "changes": ""}])

    async def review(payload):
        return next(decisions)

    _ws, events, result = await run(tmp_path, script, cfg=RunConfig(final_review=True), review=review, model=Spy(messages=iter(script)))
    assert result["status"] == "passed"
    assert any("asks for changes" in m and "also add b/y.py" in m for m in seen)  # the Project Manager received the note
    rounds = [e["round"] for e in events.since(0) if e["type"] == "review_requested"]
    assert rounds == [1, 2]
    z = zipfile.ZipFile(tmp_path / "p1" / "runs" / "r1" / "delivery.zip")
    assert {"a/x.py", "b/y.py"} <= set(z.namelist())  # the extra work is in what was delivered
    assert "also add b/y.py" in [e["text"] for e in events.since(0) if e["type"] == "review_changes_requested"]


async def test_if_the_changes_cannot_be_made_the_run_fails_instead_of_asking_again(tmp_path):
    script = [*two_step_script(), AIMessage(content="I could not do that.\n---\nstatus: fail\nreason: not possible\n---")]

    async def review(payload):
        return {"accept": False, "changes": "do the impossible"}

    _, events, result = await run(tmp_path, script, cfg=RunConfig(final_review=True), review=review)
    assert (result["status"], result["end_reason"]) == ("escalated", "pm_failed")
    assert types(events).count("review_requested") == 1 and "delivery_ready" not in types(events)


async def test_the_person_is_asked_at_most_max_review_rounds_times(tmp_path):
    script = [
        *two_step_script(),
        AIMessage(content="Tweaked.\n---\nstatus: pass\nreason: ok\n---"),
    ]

    async def review(payload):
        return {"accept": False, "changes": "again"}

    _, events, result = await run(tmp_path, script, cfg=RunConfig(final_review=True, max_review_rounds=1), review=review)
    assert types(events).count("review_requested") == 1 and result["status"] == "passed"  # no endless loop


@pytest.mark.parametrize("cfg_kwargs", [{"final_review": False}, {"final_review": True}])
async def test_no_review_when_it_is_switched_off_or_nobody_can_answer(tmp_path, cfg_kwargs):
    _, events, result = await run(tmp_path, two_step_script(), cfg=RunConfig(**cfg_kwargs), review=None)
    assert result["status"] == "passed" and "review_requested" not in types(events)


async def test_no_review_for_a_run_that_did_not_pass(tmp_path):
    async def review(payload):
        raise AssertionError("a failed run must not ask for a review")

    script = [AIMessage(content="Could not.\n---\nstatus: fail\nreason: broken\n---")]
    _, _, result = await run(tmp_path, script, cfg=RunConfig(final_review=True, max_nudges=0), review=review)
    assert result["status"] == "escalated"


# ---------------------------------------------------------------- plan first


async def test_delegating_before_planning_is_refused_and_the_plan_comes_first(tmp_path):
    """Seen with the real 9B model: it skipped write_todos and went straight to delegating, so there was no plan."""
    seen: list[str] = []

    class Spy(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.extend(str(m.content) for m in messages if isinstance(m, ToolMessage))
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    script = [
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**", "k0"),  # no plan yet: refused
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: create a/x.py", "status": "in_progress"}]})),
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**", "k1"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    ws, events, result = await run(tmp_path, script, cfg=RunConfig(require_plan=True), model=Spy(messages=iter(script)))
    assert result["status"] == "passed" and (ws.work / "a" / "x.py").exists()
    order = types(events)
    assert order.count("plan_required") == 1 and order.index("plan_required") < order.index("todos_updated") < order.index("task_started")
    assert any(m.startswith("Plan first.") for m in seen)  # the Project Manager was told what to do
    assert len(result["task_log"].tasks) == 1  # the refused delegation was not counted as work


async def test_a_project_manager_that_will_not_plan_is_let_through_with_a_warning(tmp_path):
    script = [
        delegate("backend-developer", "One.", "k0"),
        delegate("backend-developer", "One.", "k1"),
        delegate("backend-developer", "One.", "k2"),  # third try: allowed
        AIMessage(content=PASS),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(require_plan=True, max_plan_refusals=2))
    order = types(events)
    assert order.count("plan_required") == 2 and "plan_warning" in order and result["status"] == "passed"


async def test_planning_is_not_enforced_when_switched_off(tmp_path):
    script = [delegate("backend-developer", "One.\nWRITES: a/**"), AIMessage(content=PASS), AIMessage(content=PASS)]
    _, events, _ = await run(tmp_path, script, cfg=RunConfig(require_plan=False))
    assert "plan_required" not in types(events)


# ---------------------------------------------------------------- waiting for the person is not run time


async def test_time_spent_waiting_for_the_final_review_does_not_count_against_the_run_time_limit(tmp_path):
    """Found on a real run: it finished its work, waited for the person's review, and was ended by the run time limit
    (`run_timeout`) without ever delivering the zip."""
    async def slow_review(payload):
        await asyncio.sleep(3.0)  # far longer than the whole run's time limit below
        return {"accept": True, "changes": ""}

    _, events, result = await run(tmp_path, two_step_script(), cfg=RunConfig(final_review=True, run_timeout_s=2.0), review=slow_review)
    assert (result["status"], result["end_reason"]) == ("passed", "all_passed")
    assert "delivery_ready" in types(events)


async def test_time_spent_waiting_for_plan_approval_does_not_count_either(tmp_path):
    async def slow_approve(payload):
        await asyncio.sleep(3.0)
        return {"approved": True}

    script = [
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: x", "status": "pending"}]})),
        delegate("backend-developer", "Do it.\nWRITES: a/**"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),  # real work, so the task evaluation passes
        AIMessage(content=PASS),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]
    _, _, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True, run_timeout_s=2.0), approve=slow_approve)
    assert result["status"] == "passed"


async def test_the_time_limit_still_applies_to_work(tmp_path):
    class Slow(ScriptedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            await asyncio.sleep(2)
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    _, _, result = await run(tmp_path, [AIMessage(content=PASS)], cfg=RunConfig(run_timeout_s=0.6, max_nudges=0), model=Slow(messages=iter([AIMessage(content=PASS)])))
    assert (result["status"], result["end_reason"]) == ("escalated", "run_timeout")


# ---------------------------------------------------------------- the retry loop

def failing_then_fixed_script() -> list:
    return [
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"),
        AIMessage(content=FAIL),  # the specialist reports failure
        AIMessage(content="Could not do it.\n---\nstatus: fail\nreason: broken\n---"),  # the Project Manager stops
        delegate("backend-developer", "Create a/x.py, this time with the import fixed.\nWRITES: a/x.py", "k2"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content="Fixed.\n---\nstatus: pass\nreason: all passed\n---"),
    ]


async def test_failed_work_goes_back_to_the_project_manager_with_the_reason_and_is_fixed(tmp_path):
    cfg = RunConfig(max_fix_rounds=2, max_nudges=0)
    ws, events, result = await run(tmp_path, failing_then_fixed_script(), cfg=cfg)
    asked = [e for e in events.since(0) if e["type"] == "retry_requested"]
    assert len(asked) == 1 and "broken" in asked[0]["message"] and "try 1 of 3" in asked[0]["message"]
    assert (ws.work / "a" / "x.py").exists()
    assert (result["status"], result["end_reason"]) == ("passed", "all_passed")


async def test_the_retry_loop_is_off_unless_switched_on(tmp_path):
    _, events, result = await run(tmp_path, failing_then_fixed_script()[:3], cfg=RunConfig(max_nudges=0))
    assert "retry_requested" not in types(events)
    assert result["status"] == "escalated"


async def test_the_retry_loop_stops_after_max_fix_rounds_and_the_run_escalates(tmp_path):
    script = [
        delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"),
        AIMessage(content=FAIL),
        AIMessage(content="Could not.\n---\nstatus: fail\nreason: broken\n---"),
        delegate("backend-developer", "Try again.\nWRITES: a/x.py", "k2"),
        AIMessage(content=FAIL),
        AIMessage(content="Still not.\n---\nstatus: fail\nreason: broken\n---"),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(max_fix_rounds=1, max_nudges=0))
    assert types(events).count("retry_requested") == 1
    assert result["status"] == "escalated"


async def test_no_retry_is_asked_when_the_task_has_no_tries_left(tmp_path):
    script = [delegate("backend-developer", "Create a/x.py.\nWRITES: a/**"), AIMessage(content=FAIL), AIMessage(content="No.\n---\nstatus: fail\nreason: broken\n---")]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(max_fix_rounds=2, max_attempts=1, max_nudges=0))
    assert "retry_requested" not in types(events)
    assert result["status"] == "escalated"


# ---------------------------------------------------------------- a note on the plan that is only a question

async def test_a_question_about_the_plan_is_answered_and_a_plan_is_shown_again_instead_of_ending_the_run(tmp_path):
    """Seen live: the person answered the plan with 'How it will run?', the Project Manager replied in words only,
    and the run ended with no plan approved and no final status."""
    answers = iter([{"approved": False, "feedback": "How will it run?"}, {"approved": True}])
    shown = []

    async def approve(payload):
        shown.append(payload["todos"])
        return next(answers)

    script = [
        calls(tc("write_todos", {"todos": [{"content": "A", "status": "pending"}]})),
        delegate("backend-developer", "One.\nWRITES: a/**", "k1"),  # rejected with the person's question
        AIMessage(content="It runs with `python a/x.py`."),  # words only: no plan, no delegation
        calls(tc("write_todos", {"todos": [{"content": "A", "status": "pending"}]})),  # asked once to answer and plan
        delegate("backend-developer", "One.\nWRITES: a/**", "k2"),
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content=PASS),
    ]
    ws, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True, max_nudges=0), approve=approve)
    order = types(events)
    assert order.count("plan_answer_requested") == 1 and len(shown) == 2
    assert order.index("plan_changes_requested") < order.index("plan_answer_requested") < order.index("plan_approved")
    assert (ws.work / "a" / "x.py").exists() and result["status"] == "passed"


async def test_a_note_on_the_plan_is_not_chased_forever(tmp_path):
    async def approve(payload):
        return {"approved": False, "feedback": "Why?"}

    script = [
        calls(tc("write_todos", {"todos": [{"content": "A", "status": "pending"}]})),
        delegate("backend-developer", "One.\nWRITES: a/**"),
        AIMessage(content="Because."),
    ] + [AIMessage(content="Still because.")] * 4
    _, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True, max_nudges=0, max_plan_replies=2), approve=approve)
    assert types(events).count("plan_answer_requested") == 2
    assert result["status"] == "escalated"


# ---------------------------------------------------------------- a slow or briefly absent model server

class FlakyModel(ScriptedModel):
    """Times out the first `failures` calls, then plays the script. Records what the successful calls were sent."""

    failures: int = 0
    seen: list = Field(default_factory=list)

    async def _agenerate(self, messages, *args, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://model/v1/chat/completions"))
        self.seen.append([str(m.content) for m in messages if isinstance(m, HumanMessage)])
        return await super()._agenerate(messages, *args, **kwargs)


async def test_a_model_timeout_on_the_project_managers_call_is_retried_and_the_request_is_not_sent_twice(tmp_path):
    script = [delegate("backend-developer", "One.\nWRITES: a/**"), calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})), AIMessage(content=PASS), AIMessage(content=PASS)]
    model = FlakyModel(messages=iter(script), failures=2, seen=[])
    ws, _, result = await run(tmp_path, script, cfg=RunConfig(max_nudges=0), model=model)
    assert result["status"] == "passed" and (ws.work / "a" / "x.py").exists()
    first = model.seen[0]
    assert sum("Request:" in text for text in first) == 1


async def test_a_model_that_stays_away_stops_the_run_as_resumable_not_as_a_crash(tmp_path):
    model = FlakyModel(messages=iter([]), failures=99, seen=[])
    _, events, result = await run(tmp_path, [], cfg=RunConfig(max_model_retries=2, max_nudges=0), model=model)
    assert (result["status"], result["end_reason"]) == ("escalated", "model_unavailable")
    assert "report_ready" in types(events) and "Resume the run" in result["summary"] + REASONS["model_unavailable"]


async def test_the_person_is_never_asked_to_approve_an_empty_plan(tmp_path):
    """Seen live: the Project Manager delegated before writing a plan, the approval gate asked about an empty to-do list,
    and the real plan was written only after it had been approved."""
    asked = []

    async def approve(payload):
        asked.append(payload["todos"])
        return {"approved": True}

    script = [
        delegate("backend-developer", "One.\nWRITES: a/**", "k1"),  # no plan yet: refused, and nobody is asked
        calls(tc("write_todos", {"todos": [{"content": "Backend Developer: make a", "status": "pending"}]})),
        delegate("backend-developer", "One.\nWRITES: a/**", "k2"),  # now the plan is put to the person
        calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"})),
        AIMessage(content=PASS),
        AIMessage(content=PASS),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True, require_plan=True, max_nudges=0), approve=approve)
    assert asked == [[{"content": "Backend Developer: make a", "status": "pending"}]]
    order = types(events)
    assert order.index("plan_required") < order.index("todos_updated") < order.index("plan_approval_requested") < order.index("plan_approved") < order.index("task_started")
    assert result["status"] == "passed"
