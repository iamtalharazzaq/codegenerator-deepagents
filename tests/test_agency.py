"""The agency on top of the Project Manager: contracts (AFTER / RETRY / DONE), independent evaluation, replanning
context, reassignment, and plan approval that survives a restart. All run through the real deepagents machinery with
scripted models; only the model's words are scripted."""

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.tools.workspace import Workspace, git
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from test_demo_and_server import CodeAwareSandbox
from test_team import calls, tc

from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.task import TaskLog, load_task_log
from orchestrator.team import run_team

PM_MARK = "You are the Project Manager"


def ok(text: str = "Done.") -> AIMessage:
    return AIMessage(content=f"{text}\n---\nstatus: pass\nreason: ok\n---")


def delegate(role: str, description: str, call_id: str = "k1") -> AIMessage:
    return calls(tc("task", {"description": description, "subagent_type": role}, call_id))


def todos() -> AIMessage:
    return calls(tc("write_todos", {"todos": [{"content": "Backend Developer: build it", "status": "in_progress"}]}))


def task_ids(messages: list[Any]) -> list[str]:
    """The ids the Project Manager has been told so far, from the `[task <id> | ...]` line of each reply."""
    return [m for msg in messages if isinstance(msg, ToolMessage) for m in re.findall(r"\[task ([0-9a-f]{8})", str(msg.content))]


def pm_steps(*steps: Callable[[list[Any]], AIMessage]) -> Callable[[list[Any]], AIMessage]:
    """A Project Manager whose n-th reply is steps[n] (n counts its own earlier replies in the checkpointed history)."""
    def pm(messages: list[Any]) -> AIMessage:
        return steps[sum(isinstance(m, AIMessage) for m in messages)](messages)

    return pm


def worker(messages: list[Any]) -> AIMessage:
    """A specialist that does what its brief says: `CLAIM_ONLY` claims success without doing anything, `FAIL` fails,
    otherwise it writes a file inside its WRITES scope and passes."""
    brief = str(next(m.content for m in messages if isinstance(m, HumanMessage)))
    if "CLAIM_ONLY" in brief:
        return ok("All done.")
    if "FAIL" in brief:
        return AIMessage(content="It broke.\n---\nstatus: fail\nreason: it broke\n---")
    if any(isinstance(m, ToolMessage) for m in messages):
        return ok("Wrote it.")
    scope = re.search(r"WRITES:\s*(\w+)/", brief)
    return calls(tc("write_file", {"file_path": f"/{scope.group(1) if scope else 'notes'}/f.py", "content": "x = 1\n"}, "w1"))


class Playbook(BaseChatModel):
    """Plays the Project Manager (`pm`) and every specialist (`specialist`), told apart by the system prompt."""

    pm: Any
    specialist: Any = worker
    hang: Any = None  # hang(is_pm, messages) -> True: this call never returns (a process that dies mid-way)
    briefs: list[str] = Field(default_factory=list)  # what each specialist was asked, in order
    pm_saw: list[str] = Field(default_factory=list)  # every tool reply the Project Manager read

    @property
    def _llm_type(self) -> str:
        return "playbook"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Playbook":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # pragma: no cover
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = str(next(m.content for m in messages if isinstance(m, SystemMessage)))
        is_pm = PM_MARK in system
        if self.hang is not None and self.hang(is_pm, messages):
            await asyncio.Event().wait()
        if is_pm:
            self.pm_saw += [str(m.content) for m in messages if isinstance(m, ToolMessage) and str(m.content) not in self.pm_saw]
            reply = self.pm(messages)
        else:
            if not any(isinstance(m, ToolMessage) for m in messages):
                self.briefs.append(str(next(m.content for m in messages if isinstance(m, HumanMessage))))
            reply = self.specialist(messages)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def make_state(tmp_path: Path, model: Playbook, cfg: RunConfig | None = None, **extra: Any) -> dict[str, Any]:
    ws = Workspace(tmp_path, "p1")
    ws.create()
    if not (ws.work / ".git").exists():
        ws.init_git()
    log_file = ws.path / "runs" / "r1" / "task_log.json"
    return {
        "request": "build it", "workspace": ws, "run_id": "r1", "model": model,
        "task_log": load_task_log(log_file) if log_file.exists() else TaskLog("r1", "build it", []),
        "events": EventLog(ws.path / "runs" / "r1" / "events.jsonl"), "config": cfg or RunConfig(),
        "base_commit": git(ws.work, "rev-parse", "HEAD"), **extra,
    }


async def go(tmp_path: Path, model: Playbook, cfg: RunConfig | None = None, **extra: Any):
    state = make_state(tmp_path, model, cfg, **extra)
    result = await run_team(state)  # type: ignore[arg-type]
    return state["events"], result


def of_type(events: EventLog, type_: str) -> list[dict]:
    return [e for e in events.since(0) if e["type"] == type_]


def by_attempt(result: dict) -> list[tuple[str, int, str]]:
    return [(t.role, t.attempt, t.status) for t in result["task_log"].tasks]


# ---------------------------------------------------------------- the dependency graph


async def test_after_names_tasks_that_must_have_passed_and_is_checked_in_code(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("frontend-developer", "Make b.\nWRITES: b/**\nAFTER: deadbeef", "k2"),  # no such task
        lambda m: delegate("frontend-developer", f"Make b.\nWRITES: b/**\nDONE: b/f.py exists; it imports a\nAFTER: {task_ids(m)[0]}", "k3"),
        lambda m: ok("Both built."),
    )
    events, result = await go(tmp_path, Playbook(pm=pm))
    assert result["status"] == "passed"
    refused = of_type(events, "delegation_refused")
    assert len(refused) == 1 and "does not exist" in refused[0]["reason"]
    first, second = result["task_log"].tasks
    assert len(result["task_log"].tasks) == 2  # the refused delegation was not counted as work
    assert second.depends_on == (first.id,) and second.acceptance == ("b/f.py exists", "it imports a")


async def test_a_task_cannot_start_after_work_that_has_not_passed(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a. FAIL\nWRITES: a/**"),
        lambda m: delegate("frontend-developer", f"Make b.\nWRITES: b/**\nAFTER: {task_ids(m)[0]}", "k2"),
        lambda m: AIMessage(content="Stopping.\n---\nstatus: fail\nreason: a failed\n---"),
    )
    events, result = await go(tmp_path, Playbook(pm=pm))
    assert "has not passed yet (it is fail)" in of_type(events, "delegation_refused")[0]["reason"]
    assert [t.role for t in result["task_log"].tasks] == ["backend_developer"]
    assert result["status"] == "escalated"


# ---------------------------------------------------------------- retry, replanning context, reassignment


async def test_a_retry_hands_the_specialist_every_earlier_try_and_keeps_all_attempts(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a. FAIL\nWRITES: a/**"),
        lambda m: delegate("backend-developer", f"Make a, this time with care.\nWRITES: a/**\nRETRY: {task_ids(m)[0]}", "k2"),
        lambda m: ok("Fixed."),
    )
    model = Playbook(pm=pm)
    _events, result = await go(tmp_path, model)
    assert result["status"] == "passed"
    assert by_attempt(result) == [("backend_developer", 1, "fail"), ("backend_developer", 2, "pass")]
    first, second = result["task_log"].tasks
    assert second.retry_of == first.id and first.failure_kind == "agent"
    retry_brief = model.briefs[1]
    assert "This is try 2 of this work" in retry_brief and "it broke" in retry_brief and "Do not repeat what failed" in retry_brief
    # both attempts stay on disk
    runs = tmp_path / "p1" / "runs" / "r1"
    assert (runs / f"{first.id}.attempt1.md").exists() and (runs / f"{second.id}.attempt2.md").exists()
    assert f"| RETRY: {first.id}]" in "\n".join(model.pm_saw)


async def test_failed_work_can_be_reassigned_to_another_specialist(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a. FAIL\nWRITES: a/**"),
        lambda m: delegate("frontend-developer", f"Make a in another way.\nWRITES: a/**\nRETRY: {task_ids(m)[0]}", "k2"),
        lambda m: ok("Done by someone else."),
    )
    _events, result = await go(tmp_path, Playbook(pm=pm))
    assert result["status"] == "passed"
    assert by_attempt(result) == [("backend_developer", 1, "fail"), ("frontend_developer", 2, "pass")]


async def test_a_retry_must_change_something_be_of_a_failed_task_and_stop_after_the_limit(tmp_path):
    def retry(desc: str, which: int = 0):
        return lambda m: delegate("backend-developer", f"{desc}\nWRITES: a/**\nRETRY: {task_ids(m)[which]}", f"k{len(m)}")

    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a. FAIL\nWRITES: a/**"),
        retry("Make a. FAIL"),  # the same instruction: refused
        retry("Make a again. FAIL"),  # try 2: fails again
        retry("Make a a third time. FAIL", 1),  # try 3: fails again
        retry("Make a a fourth time. FAIL", 2),  # no tries left: refused
        lambda m: AIMessage(content="Giving up.\n---\nstatus: fail\nreason: could not do a\n---"),
    )
    events, result = await go(tmp_path, Playbook(pm=pm))
    reasons = [e["reason"] for e in of_type(events, "delegation_refused")]
    assert any("same instruction" in r for r in reasons) and any("3 tries already" in r for r in reasons)
    assert [t.attempt for t in result["task_log"].tasks] == [1, 2, 3]
    assert result["status"] == "escalated" and result["end_reason"] == "pm_failed"


async def test_retrying_a_task_that_did_not_fail_is_refused(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("backend-developer", f"Make a again.\nWRITES: a/**\nRETRY: {task_ids(m)[0]}", "k2"),
        lambda m: ok(),
    )
    events, _ = await go(tmp_path, Playbook(pm=pm))
    assert "not a failed task" in of_type(events, "delegation_refused")[0]["reason"]


async def test_an_infrastructure_failure_is_retried_after_a_pause(tmp_path):
    def specialist(messages):
        brief = str(next(m.content for m in messages if isinstance(m, HumanMessage)))
        if "flaky" in brief:
            raise ConnectionError("model server went away")
        return worker(messages)

    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a, flaky.\nWRITES: a/**"),
        lambda m: delegate("backend-developer", f"Make a.\nWRITES: a/**\nRETRY: {task_ids(m)[0]}", "k2"),
        lambda m: ok(),
    )
    events, result = await go(tmp_path, Playbook(pm=pm, specialist=specialist), RunConfig(retry_backoff_s=0.01))
    assert result["task_log"].tasks[0].failure_kind == "infrastructure"
    assert of_type(events, "task_retrying")[0]["wait_s"] == 0.01 and result["status"] == "passed"


# ---------------------------------------------------------------- independent evaluation


async def test_a_claimed_pass_with_nothing_done_is_overruled_and_cannot_be_delivered(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a. CLAIM_ONLY\nWRITES: a/**"),
        lambda m: ok("The Project Manager believes it."),  # it reports success anyway
    )
    model = Playbook(pm=pm)
    events, result = await go(tmp_path, model)
    task = result["task_log"].tasks[0]
    assert (task.status, task.failure_kind) == ("fail", "evaluation") and "claimed pass, but wrote no file" in task.reason
    evaluated = of_type(events, "task_evaluated")[0]
    assert evaluated["overridden"] and not evaluated["accepted"]
    assert "NOT ACCEPTED" in "\n".join(model.pm_saw)
    assert (result["status"], result["end_reason"]) == ("escalated", "no_task_passed")


async def test_a_run_cannot_pass_while_failed_work_is_unresolved(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: calls(
            tc("task", {"description": "Make a.\nWRITES: a/**", "subagent_type": "backend-developer"}, "k1"),
            tc("task", {"description": "Make b. FAIL\nWRITES: b/**", "subagent_type": "frontend-developer"}, "k2"),
        ),
        lambda m: ok("Everything is fine."),
    )
    _, result = await go(tmp_path, Playbook(pm=pm), RunConfig(concurrency=2))
    assert (result["status"], result["end_reason"]) == ("escalated", "unresolved_tasks")
    assert "Not fixed: frontend_developer" in result["summary"]
    assert "Independent checks" in (tmp_path / "p1" / "runs" / "r1" / "report.md").read_text()


def qa_that_runs(command_exit: int | None) -> Callable[[list[Any]], AIMessage]:
    """QA that runs the tests (exit code `command_exit`), or never runs them (None), then claims a pass."""
    def qa(messages: list[Any]) -> AIMessage:
        if command_exit is not None and not any(isinstance(m, ToolMessage) for m in messages):
            return calls(tc("run_tests", {"command": ["python", "-c", f"import sys; sys.exit({command_exit})"]}, "t1"))
        return ok("The tests pass.")

    return qa


async def test_qa_pass_needs_a_real_green_test_run(tmp_path):
    for exit_code, expected in [(1, "the last run_tests exited 1"), (None, "never ran run_tests"), (0, "")]:
        pm = pm_steps(
            lambda m: todos(),
            lambda m: delegate("qa-engineer", "Run the tests."),
            lambda m: ok("Tested."),
        )
        sandbox = CodeAwareSandbox()
        model = Playbook(pm=pm, specialist=qa_that_runs(exit_code))
        sub = tmp_path / f"case{exit_code}"
        sub.mkdir()
        _events, result = await go(sub, model, sandbox_client=sandbox)
        task = result["task_log"].tasks[0]
        if expected:
            assert task.status == "fail" and expected in task.reason, (exit_code, task.reason)
        else:
            assert task.status == "pass" and "run_tests ran 1 time(s), last exit 0" in task.evidence
            assert result["status"] == "passed"


async def test_without_a_sandbox_qa_cannot_be_verified_and_the_pass_says_so(tmp_path):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("qa-engineer", "Run the tests."), lambda m: ok("Tested."))
    _, result = await go(tmp_path, Playbook(pm=pm, specialist=qa_that_runs(None)))
    task = result["task_log"].tasks[0]
    assert task.status == "pass" and task.evidence[0].startswith("UNVERIFIED")


# ---------------------------------------------------------------- the registry

async def test_the_project_manager_discovers_specialists_by_capability(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: calls(tc("get_agent_capabilities", {"capability": "schema"}, "g1")),
        lambda m: delegate("database-engineer", "Design the schema.\nWRITES: db/**"),
        lambda m: ok("Designed."),
    )
    model = Playbook(pm=pm)
    _, result = await go(tmp_path, model)
    assert any("database-engineer" in saw and "schema" in saw for saw in model.pm_saw) and result["status"] == "passed"


async def test_the_new_specialists_can_be_delegated_to(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: calls(
            tc("task", {"description": "Review it.\nWRITES: docs/security.md", "subagent_type": "security-engineer"}, "k1"),
            tc("task", {"description": "Write the README.\nWRITES: README.md", "subagent_type": "technical-writer"}, "k2"),
        ),
        lambda m: ok("Both done."),
    )

    def specialist(messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return ok("Wrote it.")
        brief = str(next(m.content for m in messages if isinstance(m, HumanMessage)))
        path = "/docs/security.md" if "Review" in brief else "/README.md"
        return calls(tc("write_file", {"file_path": path, "content": "text\n"}, "w1"))

    _, result = await go(tmp_path, Playbook(pm=pm, specialist=specialist), RunConfig(concurrency=2))
    assert sorted(t.role for t in result["task_log"].tasks) == ["security_engineer", "technical_writer"]
    assert result["status"] == "passed"


# ---------------------------------------------------------------- human approval of the plan


async def test_the_person_can_send_the_plan_back_with_changes_and_is_asked_again(tmp_path):
    answers = iter([{"approved": False, "feedback": "also add tests"}, {"approved": True}])
    asked: list[Any] = []

    async def approve(payload):
        asked.append(payload["todos"])
        return next(answers)

    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),  # held for approval, then sent back
        lambda m: todos(),  # the revised plan
        lambda m: delegate("backend-developer", "Make a and tests.\nWRITES: a/**", "k2"),
        lambda m: ok(),
    )
    model = Playbook(pm=pm)
    events, result = await go(tmp_path, model, RunConfig(plan_approval=True), approve=approve)
    order = [e["type"] for e in events.since(0)]
    assert len(asked) == 2 and result["status"] == "passed"
    assert order.index("plan_changes_requested") < order.index("plan_approved") < order.index("task_started")
    assert any("also add tests" in saw for saw in model.pm_saw)  # the Project Manager was told what to change
    assert len(result["task_log"].tasks) == 1  # nothing ran before the approval


async def test_a_rejected_plan_never_runs_even_if_the_project_manager_insists(tmp_path):
    async def reject(payload):
        return {"approved": False}

    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("backend-developer", "Make a anyway.\nWRITES: a/**", "k2"),
        lambda m: AIMessage(content="Stopped.\n---\nstatus: fail\nreason: plan rejected\n---"),
    )
    _events, result = await go(tmp_path, Playbook(pm=pm), RunConfig(plan_approval=True), approve=reject)
    assert (result["status"], result["end_reason"]) == ("stopped", "plan_rejected")
    assert result["task_log"].tasks == [] and not (tmp_path / "p1" / "work" / "a").exists()


# ---------------------------------------------------------------- restart: the checkpoint carries on


def has(type_: str, objective: str = "") -> Callable[[EventLog], bool]:
    return lambda events: any(
        e["type"] == type_ and (not objective or e.get("task", {}).get("objective", "").startswith(objective)) for e in events.since(0)
    )


async def run_until(tmp_path: Path, model: Playbook, cfg: RunConfig, stop_when: Callable[[EventLog], bool], **extra: Any) -> None:
    """Start a run and kill it (cancel the task, like a process dying) as soon as `stop_when` is true of its events."""
    state = make_state(tmp_path, model, cfg, **extra)
    job = asyncio.create_task(run_team(state))  # type: ignore[arg-type]
    for _ in range(400):
        if stop_when(state["events"]):
            break
        await asyncio.sleep(0.02)
    job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    assert stop_when(state["events"])


async def test_a_plan_waiting_for_approval_survives_a_restart_and_is_asked_again(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: ok("Built."),
    )

    async def never_answered(payload):
        await asyncio.Event().wait()

    await run_until(tmp_path, Playbook(pm=pm), RunConfig(plan_approval=True), has("plan_approval_requested"), approve=never_answered)
    assert (tmp_path / "p1" / "runs" / "r1" / "task_log.json").exists()  # found by a real kill: resume needs it

    answers = []

    async def approve(payload):
        answers.append(payload["todos"])  # the todos were restored from the event log
        return {"approved": True}

    events, result = await go(tmp_path, Playbook(pm=pm), RunConfig(plan_approval=True), approve=approve)
    assert answers and answers[0][0]["content"].startswith("Backend Developer")
    types = [e["type"] for e in events.since(0)]
    assert types.count("plan_approval_requested") == 2 and types.count("plan_approved") == 1 and types.count("plan_continued") == 1
    assert result["status"] == "passed" and [t.status for t in result["task_log"].tasks] == ["pass"]


async def test_a_run_cut_off_mid_way_continues_and_does_not_redo_finished_work(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("frontend-developer", "Make b.\nWRITES: b/**", "k2"),
        lambda m: ok("Both built."),
    )

    def hang_on_b(is_pm: bool, messages: list[Any]) -> bool:
        return not is_pm and "Make b" in str(next(m.content for m in messages if isinstance(m, HumanMessage)))

    # the process dies while the second specialist is working
    await run_until(tmp_path, Playbook(pm=pm, hang=hang_on_b), RunConfig(), has("task_started", "Make b"))
    events, result = await go(tmp_path, Playbook(pm=pm))
    started = [e["task"]["objective"] for e in of_type(events, "task_started")]
    assert started.count("Make a.") == 1  # a finished before the cut: it was not run again
    assert [(t.role, t.status, t.reason) for t in result["task_log"].tasks] == [
        ("backend_developer", "pass", "ok"),
        ("frontend_developer", "fail", "interrupted before it finished"),  # the attempt that was cut off stays on record
        ("frontend_developer", "pass", "ok"),  # and its re-run passed
    ]
    assert result["status"] == "passed"  # the cut-off attempt was fixed by the later pass


# ---------------------------------------------------------------- sensitive actions need the person


def devops_running(command: list[str]) -> Callable[[list[Any]], AIMessage]:
    """DevOps that tries one command with `run_build`, then reports a pass whatever happened."""
    def devops(messages: list[Any]) -> AIMessage:
        if not any(isinstance(m, ToolMessage) for m in messages):
            return calls(tc("run_build", {"command": command, "toolchain": "tools"}, "b1"))
        return ok("Deployed.")

    return devops


def deploy_run() -> Callable[[list[Any]], AIMessage]:
    return pm_steps(lambda m: todos(), lambda m: delegate("devops-engineer", "Deploy it."), lambda m: ok("Deployed."))


async def test_a_sensitive_command_the_person_rejects_never_reaches_the_sandbox(tmp_path):
    asked: list[dict] = []

    async def approve_action(request):
        asked.append(request)
        return False

    sandbox = CodeAwareSandbox()
    model = Playbook(pm=deploy_run(), specialist=devops_running(["terraform", "apply", "-auto-approve"]))
    events, result = await go(tmp_path, model, sandbox_client=sandbox, approve_action=approve_action)
    assert sandbox.runs == []  # it was never run
    assert asked[0]["reason"] == "changes real infrastructure" and "terraform apply" in asked[0]["command"]
    assert [e["type"] for e in events.since(0) if e["type"].startswith("action_")] == ["action_approval_requested", "action_rejected"]
    task = result["task_log"].tasks[0]
    # the specialist said "Deployed", but nothing was built: the independent check overrules it
    assert task.status == "fail" and "never ran run_build" in task.reason
    assert result["status"] == "escalated"


async def test_a_sensitive_command_the_person_approves_runs(tmp_path):
    async def approve_action(request):
        return True

    sandbox = CodeAwareSandbox()
    model = Playbook(pm=deploy_run(), specialist=devops_running(["docker", "push", "registry/app:1"]))
    events, result = await go(tmp_path, model, sandbox_client=sandbox, approve_action=approve_action)
    assert len(sandbox.runs) == 1 and result["status"] == "passed"
    assert "action_approved" in [e["type"] for e in events.since(0)]


async def test_a_sensitive_command_is_refused_when_nobody_can_be_asked(tmp_path):
    sandbox = CodeAwareSandbox()
    model = Playbook(pm=deploy_run(), specialist=devops_running(["rm", "-rf", "/"]))
    events, result = await go(tmp_path, model, sandbox_client=sandbox)  # no approve_action: a missing answer is not a yes
    assert sandbox.runs == [] and result["task_log"].tasks[0].status == "fail"
    blocked = [e for e in events.since(0) if e["type"] == "guardrail_hit" and e["kind"] == "action_blocked"]
    assert blocked and "nobody can be asked" in blocked[0]["reason"]


# ---------------------------------------------------------------- changes after the work, deleting files, reading the earlier work


async def test_changes_asked_after_the_work_need_a_new_plan_the_person_approves_before_anything_runs(tmp_path):
    shown: list[list[str]] = []

    async def approve(payload):
        shown.append([t["content"] for t in payload["todos"]])
        return {"approved": True}

    reviews = iter([{"accept": False, "changes": "remove the html file"}, {"accept": True}])

    async def review(payload):
        return next(reviews)

    def replan(m: list[Any]) -> AIMessage:
        return calls(tc("write_todos", {"todos": [{"content": "Frontend Developer: delete ui.html", "status": "in_progress"}]}, "t2"))

    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: ok("Built."),
        replan,  # the change request: plan again
        lambda m: delegate("backend-developer", "Delete a/f.py.\nWRITES: a/f.py", "k2"),
        lambda m: ok("Removed."),
    )
    events, result = await go(tmp_path, Playbook(pm=pm), RunConfig(plan_approval=True, final_review=True), approve=approve, review=review)
    order = [e["type"] for e in events.since(0)]
    assert result["status"] == "passed"
    assert len(shown) == 2 and shown[1] == ["Frontend Developer: delete ui.html"]  # the person saw the new plan
    assert order.index("review_changes_requested") < order.index("plan_reopened") < order.index("plan_approval_requested", order.index("plan_reopened"))
    second_task = [i for i, t in enumerate(order) if t == "task_started"][1]
    assert order.index("plan_reopened") < order.index("plan_approval_requested", order.index("plan_reopened")) < second_task


def deleter(messages: list[Any]) -> AIMessage:
    brief = str(next(m.content for m in messages if isinstance(m, HumanMessage)))
    if any(isinstance(m, ToolMessage) for m in messages):
        return ok("Done.")
    if "Delete" in brief:
        path = re.search(r"WRITES:\s*(\S+)", brief).group(1)  # type: ignore[union-attr]
        return calls(tc("delete_file", {"file_path": f"/{path}"}, "d1"))
    return worker(messages)


async def test_a_specialist_can_delete_a_file_in_its_scope_and_the_check_sees_it_gone(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("backend-developer", "Delete a/f.py.\nWRITES: a/f.py", "k2"),
        lambda m: delegate("backend-developer", "Delete other.py.\nWRITES: a/f.py", "k3"),  # already gone: nothing to delete
        lambda m: ok(),
    )
    _events, result = await go(tmp_path, Playbook(pm=pm, specialist=deleter), RunConfig())
    tasks = result["task_log"].tasks
    assert not (tmp_path / "p1" / "work" / "a" / "f.py").exists()
    assert tasks[1].status == "pass" and tasks[1].files == ["a/f.py"] and "deleted 1 file(s): a/f.py" in tasks[1].evidence
    assert tasks[2].status == "fail"  # a deletion that did nothing is not a pass


async def test_a_delete_outside_the_tasks_scope_is_refused_and_the_file_stays(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"),
        lambda m: delegate("backend-developer", "Delete a/f.py.\nWRITES: b/**", "k2"),
        lambda m: ok(),
    )
    _events, result = await go(tmp_path, Playbook(pm=pm, specialist=deleter), RunConfig())
    assert (tmp_path / "p1" / "work" / "a" / "f.py").exists()
    assert result["task_log"].tasks[1].status == "fail"


async def test_a_task_that_follows_earlier_work_is_told_which_files_to_read_first(tmp_path):
    def second(m: list[Any]) -> AIMessage:
        return delegate("backend-developer", f"Extend a.\nWRITES: b/**\nAFTER: {task_ids(m)[0]}", "k2")

    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"), second, lambda m: ok())
    model = Playbook(pm=pm)
    await go(tmp_path, model, RunConfig())
    assert "Read these files first" in model.briefs[1] and "a/f.py" in model.briefs[1]
    assert "Read these files first" not in model.briefs[0]
