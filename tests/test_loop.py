"""The loop's rules, tested with the role calls replaced by fakes (so concurrency and timing are exact)."""

import asyncio
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from agent.tools.workspace import Workspace

import orchestrator.graph as graph_mod
from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.graph import build_graph
from orchestrator.guardrails import ToolRecord
from orchestrator.role_runner import RoleRun
from orchestrator.task import Task, TaskLog

PASS = "done\n---\nstatus: pass\nreason: ok\n---"
FAIL = "nope\n---\nstatus: fail\nreason: broken\n---"


def t(key: str, role: str = "backend_developer", objective: str | None = None, **extra: Any) -> dict:
    return {"key": key, "role": role, "objective": objective or f"do {key}", "inputs": [], "done_condition": "ok", **extra}


def plan(*tasks: dict) -> str:
    return "Because.\n```json\n" + json.dumps(list(tasks)) + "\n```"


class Harness:
    """Replaces the planner reply and the worker agent. `worker(role, objective)` returns a RoleRun (or raises)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, plans: list[str], worker=None, before=None) -> None:
        self.before = before  # runs as the agent *starts*, like real agents that write files while still working
        self.plans = iter(plans)
        self.plan_prompts: list[str] = []
        self.calls: list[str] = []  # objectives, in start order
        self.prompts: list[str] = []  # the full task prompt each agent was given
        self.active = 0
        self.max_active = 0
        self.worker = worker or (lambda role, objective: RoleRun(PASS))
        monkeypatch.setattr(graph_mod, "run_role", self._plan)
        monkeypatch.setattr(graph_mod, "run_role_traced", self._work)

    async def _plan(self, role, prompt, model, workspace, extra_tools=()):
        self.plan_prompts.append(prompt)
        return next(self.plans)

    async def _work(self, role, objective, model, workspace, tools, **kw):
        self.calls.append(objective.split("\n")[0])
        self.prompts.append(objective)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.before:
                self.before(role, objective)
            await asyncio.sleep(0.02)
            result = self.worker(role, objective)
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.active -= 1


def start(tmp_path: Path, **extra: Any) -> dict:
    ws = Workspace(tmp_path, "p1")
    ws.create()
    return {
        "request": "x", "workspace": ws, "run_id": "r1", "model": None, "last_failure": None,
        "task_log": TaskLog(run_id="r1", request="x", tasks=[]), "events": EventLog(ws.path / "runs" / "r1" / "events.jsonl"),
        **extra,
    }


async def run(state: dict) -> dict:
    return await build_graph().ainvoke(state, {"recursion_limit": 300})


def types(state: dict) -> list[str]:
    return [e["type"] for e in state["events"].since(0)]


FAN = plan(t("a", writes=["a/**"]), t("b", writes=["b/**"]), t("c", writes=["c/**"], depends_on=["a", "b"]))


async def test_independent_tasks_run_together_and_dependents_wait(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [FAN])
    result = await run(start(tmp_path, config=RunConfig(concurrency=2)))
    assert h.max_active == 2
    assert h.calls[-1] == "do c"  # c only after a and b passed
    assert result["status"] == "passed"


async def test_concurrency_one_is_sequential(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [FAN])
    await run(start(tmp_path))
    assert h.max_active == 1


async def test_overlapping_or_unscoped_writes_never_run_together(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [plan(t("a", writes=["src/**"]), t("b", writes=["src/api/**"]), t("c"))])
    result = await run(start(tmp_path, config=RunConfig(concurrency=3)))
    assert h.max_active == 1 and result["status"] == "passed"


async def test_failure_in_a_batch_replans_once_and_passed_siblings_are_not_rerun(tmp_path, monkeypatch):
    seen_b = []

    def worker(role, objective):
        if objective.startswith("do b"):
            seen_b.append(1)
            return RoleRun(FAIL if len(seen_b) == 1 else PASS)
        return RoleRun(PASS)

    h = Harness(monkeypatch, [plan(t("a", writes=["a/**"]), t("b", writes=["b/**"])), plan(t("b", objective="do b, fixed", writes=["b/**"]))], worker)
    result = await run(start(tmp_path, config=RunConfig(concurrency=2)))
    assert result["status"] == "passed"
    assert h.calls.count("do a") == 1  # the passing sibling ran once
    b = next(x for x in result["task_log"].tasks if x.objective.startswith("do b"))
    assert (b.status, b.attempt) == ("pass", 2)
    assert "do b" in h.plan_prompts[1] and "broken" in h.plan_prompts[1]


async def test_a_task_that_cannot_pass_blocks_its_dependents(tmp_path, monkeypatch):
    first = plan(t("a", writes=["a/**"]), t("b", writes=["b/**"], depends_on=["a"]))
    h = Harness(monkeypatch, [first, first], lambda role, objective: RoleRun(FAIL))
    result = await run(start(tmp_path))
    by = {x.objective: x for x in result["task_log"].tasks}
    assert by["do a"].status == "escalated" and by["do b"].status == "blocked"
    assert "do b" not in h.calls
    assert result["status"] == "escalated" and result["end_reason"] == "task_escalated"


async def test_unknown_dependency_is_sent_back_to_the_planner(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [plan(t("a", depends_on=["ghost"])), plan(t("a"))])
    result = await run(start(tmp_path))
    assert result["status"] == "passed"
    assert "ghost" in h.plan_prompts[1] and "plan_invalid" in types(result)


async def test_two_invalid_plans_in_a_row_stop_the_run(tmp_path, monkeypatch):
    Harness(monkeypatch, ["no json here", "still none"])
    result = await run(start(tmp_path))
    assert (result["status"], result["end_reason"]) == ("escalated", "planner_failed")
    assert types(result)[-1] == "run_finished"


async def test_an_empty_plan_is_reported_not_called_a_success(tmp_path, monkeypatch):
    Harness(monkeypatch, [plan()])
    result = await run(start(tmp_path))
    assert (result["status"], result["end_reason"]) == ("escalated", "empty_plan")


async def test_replan_cap_stops_a_run_that_keeps_failing(tmp_path, monkeypatch):
    roles = ["qa_engineer", "backend_developer", "frontend_developer", "devops_engineer", "database_engineer"]
    h = Harness(monkeypatch, [plan(t("x", role=r)) for r in roles], lambda role, objective: RoleRun(FAIL))
    result = await run(start(tmp_path, config=RunConfig(max_replans=3)))
    assert result["end_reason"] == "replan_cap" and result["replans"] == 3
    assert len(h.calls) == 4


async def test_replaces_keeps_the_attempt_count_across_a_role_change(tmp_path, monkeypatch):
    holder: dict[str, str] = {}
    h = Harness(monkeypatch, [], lambda role, objective: RoleRun(FAIL))
    first = plan(t("x", role="qa_engineer"))
    state = start(tmp_path)

    def replies():
        yield first
        task_id = state["task_log"].tasks[0].id  # the failed qa task
        holder["id"] = task_id
        yield plan(t("y", role="backend_developer", replaces=task_id))

    h.plans = replies()
    result = await run(state)
    # qa failed once, the backend developer took over the same task: its 2nd failure is the last, no 3rd attempt.
    live = [x for x in result["task_log"].tasks if x.status != "superseded"]
    assert [(x.role, x.status, x.attempt) for x in live] == [("backend_developer", "escalated", 2)]
    assert len(h.calls) == 2


async def test_an_agent_that_raises_is_a_failed_attempt_not_a_crashed_run(tmp_path, monkeypatch):
    calls = []

    def worker(role, objective):
        calls.append(1)
        return RuntimeError("model unavailable") if len(calls) == 1 else RoleRun(PASS)

    Harness(monkeypatch, [plan(t("a")), plan(t("a"))], worker)
    result = await run(start(tmp_path))
    assert result["status"] == "passed"
    finished = [e for e in result["events"].since(0) if e["type"] == "task_finished"]
    assert "RuntimeError: model unavailable" in finished[0]["task"]["reason"]


async def test_task_timeout_is_a_guardrail_hit_and_a_failed_attempt(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [plan(t("a")), plan(t("a"))], None)

    async def slow(role, objective, model, workspace, tools, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(graph_mod, "run_role_traced", slow)
    result = await run(start(tmp_path, config=RunConfig(task_timeout_s=0.05)))
    hits = [e for e in result["events"].since(0) if e["type"] == "guardrail_hit"]
    assert hits and hits[0]["kind"] == "task_timeout"
    assert result["task_log"].tasks[0].status == "escalated"
    assert h is not None


async def test_qa_pass_is_overridden_by_a_real_failing_exit_code(tmp_path, monkeypatch):
    bad = RoleRun(PASS, [ToolRecord("run_tests", {"command": ["pytest"]}, "exit 1\n2 failed")])
    good = RoleRun(PASS, [ToolRecord("run_tests", {"command": ["pytest"]}, "exit 0\n2 passed")])
    answers = iter([bad, good])
    Harness(monkeypatch, [plan(t("q", role="qa_engineer")), plan(t("q", role="qa_engineer"))], lambda r, o: next(answers))
    result = await run(start(tmp_path, sandbox_client=object()))
    assert result["status"] == "passed"
    kinds = [e["kind"] for e in result["events"].since(0) if e["type"] == "guardrail_hit"]
    assert kinds == ["status_overridden"]
    assert result["task_log"].tasks[0].reasons == ["run_tests exited 1"]


async def test_qa_pass_without_any_test_run_is_not_trusted(tmp_path, monkeypatch):
    Harness(monkeypatch, [plan(t("q", role="qa_engineer")), plan(t("q", role="qa_engineer"))], lambda r, o: RoleRun(PASS))
    result = await run(start(tmp_path, sandbox_client=object()))
    assert result["status"] == "escalated"
    assert "never run" in result["task_log"].tasks[0].reason


async def test_plan_approval_gates_the_first_plan_only(tmp_path, monkeypatch):
    asked = []

    async def approve(payload):
        asked.append(len(payload["tasks"]))
        return True

    answers = iter([FAIL, PASS])
    Harness(monkeypatch, [plan(t("a")), plan(t("a"))], lambda r, o: RoleRun(next(answers)))
    result = await run(start(tmp_path, config=RunConfig(plan_approval=True), approve=approve))
    assert asked == [1] and result["status"] == "passed"  # the replan did not ask again
    assert "plan_approval_requested" in types(result)


async def test_a_rejected_plan_runs_nothing(tmp_path, monkeypatch):
    async def reject(payload):
        return False

    h = Harness(monkeypatch, [plan(t("a"))])
    result = await run(start(tmp_path, config=RunConfig(plan_approval=True), approve=reject))
    assert result["status"] == "stopped" and result["end_reason"] == "plan_rejected" and h.calls == []


async def test_passed_run_writes_report_commits_and_builds_the_zip(tmp_path, monkeypatch):
    state = start(tmp_path)
    ws = state["workspace"]
    ws.init_git()

    def worker(role, objective):
        (ws.work / "app.py").write_text("print(1)\n")
        return RoleRun(PASS)

    Harness(monkeypatch, [plan(t("a"))], worker)
    base = graph_mod.git(ws.work, "rev-parse", "HEAD")
    result = await run({**state, "base_commit": base})
    runs = ws.path / "runs" / "r1"
    report = (runs / "report.md").read_text()
    assert "# Run r1: passed" in report and "app.py" in report
    assert "app.py" in zipfile.ZipFile(runs / "delivery.zip").namelist()
    assert "docs/orchestrator/report.md" in zipfile.ZipFile(runs / "delivery.zip").namelist()
    assert graph_mod.git(ws.work, "log", "--oneline", f"{base}..HEAD")  # the passed task was committed
    assert types(result)[-3:] == ["report_ready", "delivery_ready", "run_finished"]


async def test_a_secret_in_the_code_blocks_the_zip_but_not_the_report(tmp_path, monkeypatch):
    state = start(tmp_path)
    ws = state["workspace"]

    def worker(role, objective):
        (ws.work / "cfg.py").write_text('KEY = "AKIAABCDEFGHIJKLMNOP"\n')
        return RoleRun(PASS)

    Harness(monkeypatch, [plan(t("a"))], worker)
    result = await run(state)
    runs = ws.path / "runs" / "r1"
    assert not (runs / "delivery.zip").exists()
    assert "not built" in (runs / "report.md").read_text()
    assert "AKIA" not in (runs / "report.md").read_text()
    hit = next(e for e in result["events"].since(0) if e["type"] == "guardrail_hit")
    assert hit["kind"] == "secret_scan" and result["status"] == "passed"


async def test_escalated_run_has_a_report_with_evidence_and_no_zip(tmp_path, monkeypatch):
    first = plan(t("a"))
    Harness(monkeypatch, [first, first], lambda r, o: RoleRun(FAIL))
    state = start(tmp_path)
    result = await run(state)
    runs = state["workspace"].path / "runs" / "r1"
    report = (runs / "report.md").read_text()
    assert "escalated" in report and "What did not pass" in report and ".md`" in report
    assert not (runs / "delivery.zip").exists()
    assert (runs / f"{result['task_log'].tasks[0].id}.attempt2.md").exists()  # every attempt's evidence is kept


async def test_resume_at_act_does_not_replan(tmp_path, monkeypatch):
    h = Harness(monkeypatch, [])
    log = TaskLog(run_id="r1", request="x", tasks=[
        Task(id="aaaa1111", role="backend_developer", objective="do a", inputs=(), done_condition="ok"),
    ])
    result = await run(start(tmp_path, task_log=log, start_at="act"))
    assert result["status"] == "passed" and h.plan_prompts == []


async def test_events_tell_the_story_in_order(tmp_path, monkeypatch):
    Harness(monkeypatch, [plan(t("a"))])
    result = await run(start(tmp_path))
    order = types(result)
    assert order[:3] == ["plan_started", "plan_ready", "task_started"]
    assert order.index("task_started") < order.index("task_finished") < order.index("run_finished")
    started = next(e for e in result["events"].since(0) if e["type"] == "task_started")
    assert started["task"]["status"] == "in_progress" and started["task"]["attempt"] == 1  # emitted *before* the work


async def test_a_new_prerequisite_in_a_replan_does_not_trigger_another_replan(tmp_path, monkeypatch):
    """Regression: the retried task used to keep status 'fail', so when the new prerequisite passed the router saw
    a 'fail' and replanned from scratch again, looping until the dispatch cap."""
    answers = iter([FAIL, PASS, PASS])  # b fails; then x passes; then b passes
    h = Harness(
        monkeypatch,
        [plan(t("b", role="qa_engineer", writes=["tests/**"])),
         plan(t("x", writes=["backend/**"]), t("b", role="qa_engineer", writes=["tests/**"], depends_on=["x"]))],
        lambda r, o: RoleRun(next(answers)),
    )
    result = await run(start(tmp_path))
    assert result["status"] == "passed" and result["replans"] == 1
    assert len(h.plan_prompts) == 2 and h.calls == ["do b", "do x", "do b"]
    assert next(x for x in result["task_log"].tasks if x.role == "qa_engineer").attempt == 2


def _commits(ws, base: str) -> list[tuple[str, list[str]]]:
    raw = graph_mod.git(ws.work, "log", "--reverse", "--format=@@%s", "--name-only", f"{base}..HEAD")
    out = []
    for block in raw.split("@@")[1:]:
        subject, *files = [x for x in block.splitlines() if x.strip()]
        out.append((subject, files))
    return out


async def test_parallel_tasks_get_separate_commits_with_only_their_own_files(tmp_path, monkeypatch):
    """Regression (found in a live run): the first task to finish used `git add -A`, so its commit swallowed the
    sibling's files and the sibling got no commit at all. Both files exist before either task finishes."""
    state = start(tmp_path, config=RunConfig(concurrency=2))
    ws = state["workspace"]
    ws.init_git()

    def write_own_file(role, objective):
        name = objective.split("\n")[0].split()[-1]  # "a" or "b"
        (ws.work / name).mkdir(exist_ok=True)
        (ws.work / name / "f.py").write_text(name)

    Harness(monkeypatch, [plan(t("a", writes=["a/**"]), t("b", writes=["b/**"]))], before=write_own_file)
    base = graph_mod.git(ws.work, "rev-parse", "HEAD")
    await run({**state, "base_commit": base})
    commits = _commits(ws, base)
    assert sorted(files for _, files in commits) == [["a/f.py"], ["b/f.py"]]
    assert all(("do a" in s and "a/f.py" in f) or ("do b" in s and "b/f.py" in f) for s, f in commits)


async def test_files_outside_every_declared_scope_are_committed_at_the_end(tmp_path, monkeypatch):
    state = start(tmp_path)
    ws = state["workspace"]
    ws.init_git()

    def worker(role, objective):
        (ws.work / "a").mkdir(exist_ok=True)
        (ws.work / "a" / "f.py").write_text("x")
        (ws.work / "stray.txt").write_text("y")  # outside the task's declared scope
        return RoleRun(PASS)

    Harness(monkeypatch, [plan(t("a", writes=["a/**"]))], worker)
    base = graph_mod.git(ws.work, "rev-parse", "HEAD")
    await run({**state, "base_commit": base})
    commits = _commits(ws, base)
    assert commits[0][1] == ["a/f.py"] and commits[-1][0].startswith("run r1") and commits[-1][1] == ["stray.txt"]
    assert not graph_mod.git(ws.work, "status", "--porcelain")


async def test_a_stuck_agent_fails_the_attempt_with_a_clear_reason_and_a_guardrail_event(tmp_path, monkeypatch):
    from orchestrator.guardrails import AgentStuck

    answers = iter([AgentStuck("tried to write outside its scope 3 times"), RoleRun(PASS)])
    Harness(monkeypatch, [plan(t("a", writes=["greet.py"])), plan(t("a", writes=["greet.py"]))], lambda r, o: next(answers))
    result = await run(start(tmp_path))
    assert result["status"] == "passed"
    hit = next(e for e in result["events"].since(0) if e["type"] == "guardrail_hit")
    assert hit["kind"] == "agent_stuck" and "outside its scope" in hit["reason"]
    assert "outside its scope" in result["task_log"].tasks[0].reasons[0]


def test_the_task_prompt_does_not_tell_the_model_to_write_its_reply_to_a_file():
    import inspect

    source = inspect.getsource(graph_mod._run_task)
    assert "do not write it to a file" in source and "result artifact" not in source


async def test_the_agent_is_told_where_it_may_write(tmp_path, monkeypatch):
    """Found on the real model: agents guessed file names, were blocked by the write scope, and burned model rounds
    because the prompt never said which paths were allowed."""
    h = Harness(monkeypatch, [plan(t("a", writes=["server/**", "docs/api.md"]), t("b", writes=[]))])
    await run(start(tmp_path))
    scoped = next(p for p in h.prompts if p.startswith("do a"))
    assert "You may only create or edit files inside: server/**, docs/api.md" in scoped
    unscoped = next(p for p in h.prompts if p.startswith("do b"))
    assert "You may only create or edit" not in unscoped
    assert "documents stay under 80 lines" in scoped and "documents stay under 80 lines" in unscoped
