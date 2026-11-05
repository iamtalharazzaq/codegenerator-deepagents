"""The team (Project Manager deep agent + specialists as deepagents sub-agents), run for real with scripted models."""

import asyncio
import zipfile
from pathlib import Path
from typing import Any

import pytest
from agent.tools.workspace import Workspace, git
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.team import objective_of, parse_writes, resolve_role, run_team

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


async def run(tmp_path: Path, script: list, *, cfg: RunConfig | None = None, approve=None, note=None, model=None, git_repo=True):
    ws = Workspace(tmp_path, "p1")
    ws.create()
    if git_repo:
        ws.init_git()
    events = EventLog(ws.path / "runs" / "r1" / "events.jsonl")
    from orchestrator.task import TaskLog

    state: dict[str, Any] = {
        "request": "build it", "workspace": ws, "run_id": "r1", "model": model or ScriptedModel(messages=iter(script)),
        "task_log": TaskLog("r1", "build it", []), "events": events, "config": cfg or RunConfig(), "approve": approve,
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
    ws, _, result = await run(tmp_path, script)
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
    ws, events, result = await run(tmp_path, script, model=Spy(messages=iter(script)))
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
        return True

    script = [
        calls(tc("write_todos", {"todos": [{"content": "A", "status": "pending"}]})),
        delegate("backend-developer", "One.\nWRITES: a/**", "k1"),
        AIMessage(content=PASS),
        delegate("backend-developer", "Two.\nWRITES: b/**", "k2"),
        AIMessage(content=PASS),
        AIMessage(content=PASS),
    ]
    _, events, result = await run(tmp_path, script, cfg=RunConfig(plan_approval=True), approve=approve)
    assert asked == [[{"content": "A", "status": "pending"}]] and result["status"] == "passed"
    order = types(events)
    assert order.index("plan_approval_requested") < order.index("plan_approved") < order.index("task_started")


async def test_a_rejected_plan_delegates_nothing_and_the_run_is_stopped(tmp_path):
    async def reject(payload):
        return False

    script = [
        delegate("backend-developer", "One.\nWRITES: a/**"),
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
    _, events, result = await run(tmp_path, [AIMessage(content=final)])
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
    await run(tmp_path, [AIMessage(content=PASS)], note=note, model=Spy(messages=iter([AIMessage(content=PASS)])))
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
    _, events, result = await run(tmp_path, script)
    said = [e["text"] for e in events.since(0) if e["type"] == "pm_said"]
    assert said == ["I will start with the backend because the UI depends on it."]  # once, and not the final reply
    finished = next(e for e in events.since(0) if e["type"] == "run_finished")
    assert finished["summary"] == "Done."  # the final reply without its status block
    assert types(events).index("pm_said") < types(events).index("task_started")
