"""Re-planning after a failure: a failed piece of work comes back to the Project Manager, which must say it is a retry (so
the count of tries holds), a plan that gains steps mid-run is put to the person again, and a DONE line that names what
a file defines is checked by code."""

from test_agency import Playbook, delegate, go, of_type, ok, pm_steps, task_ids, todos
from test_team import calls, tc

from orchestrator.config import RunConfig
from orchestrator.evaluate import check_acceptance

FAIL = "It broke.\n---\nstatus: fail\nreason: it broke\n---"


def failing_worker(messages):
    return AIMessage_fail()


def AIMessage_fail():
    from langchain_core.messages import AIMessage

    return AIMessage(content=FAIL)


def writer(messages):
    from langchain_core.messages import ToolMessage

    if any(isinstance(m, ToolMessage) for m in messages):
        return ok("Wrote it.")
    return calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"}, "w1"))


def fail_first_then_write(messages):
    from langchain_core.messages import HumanMessage

    brief = str(next(m.content for m in messages if isinstance(m, HumanMessage)))
    return writer(messages) if "RETRY" in brief or "again" in brief else AIMessage_fail()


# ---------------------------------------------------------------- a retry must say it is one

async def test_repeating_failed_work_without_retry_is_refused_and_then_accepted_with_it(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**", "k1"),
        lambda m: delegate("backend-developer", "Make a, again, with care.\nWRITES: a/**", "k2"),  # a retry that does not say so
        lambda m: delegate("backend-developer", f"Make a again.\nWRITES: a/**\nRETRY: {task_ids(m)[0]}", "k3"),
        lambda m: ok(),
    )
    events, result = await go(tmp_path, Playbook(pm=pm, specialist=fail_first_then_write), RunConfig(max_nudges=0))
    refused = of_type(events, "delegation_refused")
    assert len(refused) == 1 and "RETRY:" in refused[0]["reason"]
    assert [(t.attempt, t.status) for t in result["task_log"].tasks] == [(1, "fail"), (2, "pass")]  # the count of tries held


async def test_failed_work_with_no_tries_left_cannot_be_started_again_under_a_new_name(tmp_path):
    def retry_of_last(m):
        n = len(task_ids(m))
        return delegate("backend-developer", f"Make a, in way number {n}.\nWRITES: a/**\nRETRY: {task_ids(m)[-1]}", f"r{n}")

    pm = pm_steps(
        lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**", "k1"), retry_of_last, retry_of_last,
        lambda m: delegate("backend-developer", "Make a, once more.\nWRITES: a/**", "k9"),  # three tries are used: this is refused
        lambda m: AIMessage_report(),
    )
    events, result = await go(tmp_path, Playbook(pm=pm, specialist=failing_worker), RunConfig(max_nudges=0, max_fix_rounds=0))
    assert [t.attempt for t in result["task_log"].tasks] == [1, 2, 3]
    assert any("tries already" in e["reason"] for e in of_type(events, "delegation_refused"))


def AIMessage_report():
    from langchain_core.messages import AIMessage

    return AIMessage(content="Could not.\n---\nstatus: fail\nreason: three tries failed\n---")


async def test_different_work_for_the_same_specialist_is_not_mistaken_for_a_retry(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**", "k1"),
        lambda m: delegate("backend-developer", "Make b.\nWRITES: b/**", "k2"),  # other files: new work
        lambda m: ok(),
    )
    events, _ = await go(tmp_path, Playbook(pm=pm, specialist=failing_worker), RunConfig(max_nudges=0, max_fix_rounds=0))
    assert not of_type(events, "delegation_refused")


# ---------------------------------------------------------------- a plan that changes mid-run is put to the person again

def plan(*items):
    return calls(tc("write_todos", {"todos": [{"content": c, "status": s} for c, s in items]}))


async def test_a_plan_that_gains_a_step_after_work_started_is_put_to_the_person_again(tmp_path):
    asked = []

    async def approve(payload):
        asked.append([t["content"] for t in payload["todos"]])
        return {"approved": True}

    pm = pm_steps(
        lambda m: plan(("Backend Developer: make a/x.py", "pending")),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**", "k1"),
        lambda m: plan(("Backend Developer: make a/x.py", "completed")),  # only a status changed: nobody is asked
        lambda m: plan(("Backend Developer: make a/x.py", "completed"), ("QA Engineer: test a/x.py in t/test_x.py", "pending")),  # a new step
        lambda m: delegate("backend-developer", "Test it.\nWRITES: a/**", "k2"),
        lambda m: ok(),
    )
    events, result = await go(tmp_path, Playbook(pm=pm, specialist=writer), RunConfig(plan_approval=True, max_nudges=0), approve=approve)
    assert len(asked) == 2 and "QA Engineer: test a/x.py in t/test_x.py" in asked[1]
    revised = of_type(events, "plan_revised")
    assert len(revised) == 1 and "QA Engineer" in revised[0]["added"][0]
    assert result["status"] == "passed"


async def test_a_revised_plan_is_only_recorded_when_approval_is_off(tmp_path):
    pm = pm_steps(
        lambda m: plan(("Backend Developer: make a/x.py", "pending")),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**", "k1"),
        lambda m: plan(("Backend Developer: make a/x.py", "completed"), ("QA Engineer: test it", "pending")),
        lambda m: ok(),
    )
    events, _ = await go(tmp_path, Playbook(pm=pm, specialist=writer), RunConfig(max_nudges=0))
    assert len(of_type(events, "plan_revised")) == 1 and not of_type(events, "plan_approval_requested")


# ---------------------------------------------------------------- DONE lines that code can check

def test_a_done_line_that_names_what_a_file_defines_is_checked(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    evidence, problems = check_acceptance(("calc.py defines functions: add(a, b), divide(a, b) that return numbers",), tmp_path)
    assert problems == ["DONE says calc.py defines divide, but it does not"] and not evidence
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    return a / b\n")
    evidence, problems = check_acceptance(("calc.py defines functions: add(a, b), divide(a, b) that return numbers",), tmp_path)
    assert not problems and evidence == ["DONE checked: calc.py defines add, divide"]
    assert check_acceptance(("nope.py defines add",), tmp_path)[1] == ["DONE says nope.py defines add, but that file does not exist"]


def test_a_done_line_in_any_other_form_is_never_failed_for_being_unclear(tmp_path):
    assert check_acceptance(("the tests pass", "it works well", "calc.py is fast"), tmp_path) == ([], [])


async def test_a_task_that_does_not_define_what_its_done_line_says_fails_and_goes_back_for_a_retry(tmp_path):
    pm = pm_steps(
        lambda m: todos(),
        lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**\nDONE: a/x.py defines add, divide", "k1"),
        lambda m: ok(),
    )
    _, result = await go(tmp_path, Playbook(pm=pm, specialist=writer), RunConfig(max_nudges=0, max_fix_rounds=0))
    task = result["task_log"].tasks[0]
    assert task.status == "fail" and task.failure_kind == "evaluation" and "defines add, divide, but it does not" in task.reason
