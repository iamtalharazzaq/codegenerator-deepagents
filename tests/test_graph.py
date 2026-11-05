from pathlib import Path
from typing import Any

from agent.tools.workspace import Workspace
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from orchestrator.config import RunConfig
from orchestrator.graph import MAX_TOTAL_DISPATCHES, build_graph
from orchestrator.runs import run_dir
from orchestrator.task import TaskLog, load_task_log


class ScriptedModel(GenericFakeChatModel):
    """`GenericFakeChatModel` raises on `bind_tools`, which `create_deep_agent` always calls.
    Same minimal subclass as `tests/test_role_runner.py` (and codewright's test_team.py)."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def plan_message(tasks_json: str) -> AIMessage:
    return AIMessage(content=f"```json\n{tasks_json}\n```")


def assert_all_consumed(model: ScriptedModel) -> None:
    # The scripted iterator must be exhausted: the graph asked for exactly the scripted messages.
    assert next(model.messages, None) is None


async def test_happy_path_runs_one_task_to_done(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    model = ScriptedModel(messages=iter([
        plan_message('[{"role": "product_manager", "objective": "write 1 story", '
                      '"inputs": [], "done_condition": "stories written"}]'),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: 1 story written\n---"),
    ]))
    graph = build_graph()
    result = await graph.ainvoke({"request": "add a wishlist", "workspace": ws, "run_id": "r1",
                                   "model": model, "task_log": TaskLog(run_id="r1", request="add a wishlist", tasks=[]),
                                   "last_failure": None})
    assert result["task_log"].tasks[0].status == "pass"
    assert_all_consumed(model)
    # The task log is persisted under runs/<run_id>/ and the task's artifact is there too.
    saved = load_task_log(run_dir(ws, "r1") / "task_log.json")
    assert saved.tasks[0].status == "pass"
    assert (run_dir(ws, "r1") / f"{saved.tasks[0].id}.md").exists()


async def test_one_failure_then_replan_then_pass(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    model = ScriptedModel(messages=iter([
        plan_message('[{"role": "qa_engineer", "objective": "add a test", '
                      '"inputs": [], "done_condition": "test passes"}]'),
        AIMessage(content="Added test.\n---\nstatus: fail\nreason: 1 test still red\n---"),
        plan_message('[{"role": "qa_engineer", "objective": "fix the test", '
                      '"inputs": [], "done_condition": "test passes"}]'),
        AIMessage(content="Fixed.\n---\nstatus: pass\nreason: all green\n---"),
    ]))
    result = await build_graph().ainvoke({"request": "x", "workspace": ws, "run_id": "r2", "model": model,
                                           "task_log": TaskLog(run_id="r2", request="x", tasks=[]), "last_failure": None})
    assert result["task_log"].tasks[-1].status == "pass"
    assert result["task_log"].tasks[-1].attempt == 2
    assert_all_consumed(model)


async def test_second_failure_on_the_same_task_escalates_without_a_third_attempt(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    fail = AIMessage(content="Nope.\n---\nstatus: fail\nreason: still broken\n---")
    model = ScriptedModel(messages=iter([
        plan_message('[{"role": "qa_engineer", "objective": "fix it", "inputs": [], "done_condition": "passes"}]'),
        fail,
        plan_message('[{"role": "qa_engineer", "objective": "fix it", "inputs": [], "done_condition": "passes"}]'),
        fail,
    ]))
    result = await build_graph().ainvoke({"request": "x", "workspace": ws, "run_id": "r3", "model": model,
                                           "task_log": TaskLog(run_id="r3", request="x", tasks=[]), "last_failure": None})
    assert result["task_log"].tasks[-1].status == "escalated"
    assert result["task_log"].tasks[-1].attempt == 2
    assert len(result["task_log"].tasks) == 1
    assert result["last_failure"] is None
    # The model was never asked for a 3rd plan after the 2nd failure: exactly the 4 scripted messages were consumed
    # (a 5th request would have raised from the exhausted iterator).
    assert_all_consumed(model)


def _start(ws: Workspace, run_id: str, model: ScriptedModel) -> dict:
    return {"request": "x", "workspace": ws, "run_id": run_id, "model": model,
            "task_log": TaskLog(run_id=run_id, request="x", tasks=[]), "last_failure": None}


async def test_project_manager_tasks_are_never_dispatched(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    model = ScriptedModel(messages=iter([
        plan_message('[{"role": "project_manager", "objective": "plan more", "inputs": [], "done_condition": "planned"},'
                     ' {"role": "product_manager", "objective": "write 1 story", "inputs": [], "done_condition": "ok"}]'),
        AIMessage(content="Done.\n---\nstatus: pass\nreason: ok\n---"),
    ]))
    result = await build_graph().ainvoke(_start(ws, "r4", model))
    assert [t.role for t in result["task_log"].tasks] == ["product_manager"]
    assert result["task_log"].tasks[0].status == "pass"
    assert_all_consumed(model)


async def test_empty_first_plan_finishes_without_dispatching(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    model = ScriptedModel(messages=iter([plan_message("[]")]))
    result = await build_graph().ainvoke(_start(ws, "r5", model))
    assert result["task_log"].tasks == []
    assert result["last_failure"] is None
    assert_all_consumed(model)


async def test_empty_replan_after_a_failure_escalates(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    model = ScriptedModel(messages=iter([
        plan_message('[{"role": "qa_engineer", "objective": "fix it", "inputs": [], "done_condition": "passes"}]'),
        AIMessage(content="Nope.\n---\nstatus: fail\nreason: still broken\n---"),
        plan_message("[]"),
    ]))
    result = await build_graph().ainvoke(_start(ws, "r6", model))
    assert [(t.status, t.attempt) for t in result["task_log"].tasks] == [("escalated", 1)]
    assert result["last_failure"] is not None
    assert_all_consumed(model)


async def test_role_switching_hits_the_run_level_dispatch_cap(tmp_path: Path):
    ws = Workspace(tmp_path, "p1"); ws.create()
    fail = AIMessage(content="Nope.\n---\nstatus: fail\nreason: still broken\n---")
    roles = ["qa_engineer", "backend_developer"]
    script: list[AIMessage] = []
    for i in range(MAX_TOTAL_DISPATCHES):
        role = roles[i % 2]
        script.append(plan_message(f'[{{"role": "{role}", "objective": "fix it", "inputs": [], '
                                   '"done_condition": "passes"}]'))
        script.append(fail)
    model = ScriptedModel(messages=iter(script))
    state = {**_start(ws, "r7", model), "config": RunConfig(max_replans=100)}  # the replan cap would stop it first
    result = await build_graph().ainvoke(state, {"recursion_limit": 200})
    assert result["total_dispatches"] == MAX_TOTAL_DISPATCHES
    assert result["task_log"].tasks[-1].status == "escalated"
    assert result["task_log"].tasks[-1].attempt == 1  # escalated by the run cap, not the per-task cap
    assert_all_consumed(model)
