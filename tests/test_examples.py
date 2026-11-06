"""Few-shot examples: the library is valid, the choice is deterministic and optional, it respects the token budget and
the context window, and what was supplied is recorded. (Whether examples HELP is measured on the real model, not here:
see docs/EXAMPLES-EVAL.md.)"""

import pytest
from test_agency import Playbook, delegate, go, of_type, ok, pm_steps, todos
from test_context_budget import Probe, tokens

from orchestrator.config import RunConfig
from orchestrator.examples import (
    HEADING,
    MAX_EXAMPLES,
    estimate_tokens,
    format_examples,
    load_examples,
    select_examples,
)
from orchestrator.roles import discover_roles, load_role, specialists

# What a specialist is sent before any work (system prompt + tools), in the same estimate as test_context_budget.
ROLE_BUDGET_TOKENS = 1200


def test_every_example_is_well_formed_and_fits_the_budget():
    seen = set()
    for folder in discover_roles():
        role = load_role(folder)
        for e in load_examples(folder):
            assert e.id not in seen, f"duplicate example id {e.id}"
            seen.add(e.id)
            assert set(e.task_types) <= set(role.task_types), f"{e.id}: task type not in {folder}'s config.yaml"
            assert e.when in ("first", "retry", "any") and e.tags and e.task and e.good
            assert estimate_tokens(format_examples([e])) <= 250, f"{e.id} alone is over the example budget"
    assert len(seen) >= 12  # every specialist has at least one


def test_every_specialist_has_the_capability_record_the_project_manager_chooses_by():
    for folder in specialists():
        role = load_role(folder)
        assert role.use_when and role.task_types and role.inputs and role.deliverables and role.restrictions, folder
        assert len(role.use_when.split()) <= 18, f"{folder}: use_when must stay short (it is in every Project Manager call)"


def ids(chosen):
    return [e.id for e in chosen]


def test_a_matching_task_gets_the_matching_example_and_an_unrelated_task_gets_none():
    assert ids(select_examples("qa_engineer", "Write tests for calculator.py and run them")) == ["qa-tests-for-a-function"]
    assert select_examples("qa_engineer", "Compose a poem about the sea") == []
    assert select_examples("qa_engineer", "Write documentation") == []  # one weak signal is not enough


def test_a_retry_gets_retry_examples_and_a_first_try_does_not():
    objective = "Re-run the tests for calculator.py after the fix"
    assert "qa-code-is-wrong" in ids(select_examples("qa_engineer", objective, retry=True))
    assert "qa-code-is-wrong" not in ids(select_examples("qa_engineer", objective, retry=False))
    first = select_examples("qa_engineer", "Write tests for calculator.py and run them", retry=True)
    assert "qa-tests-for-a-function" not in ids(first)  # a `for: first` example is not used on a retry


def test_examples_belong_to_their_role():
    assert select_examples("backend_developer", "Write tests for calculator.py and run them") == []


def test_the_choice_is_deterministic_and_never_exceeds_the_token_budget_or_three_examples():
    objective = "Write tests for calculator.py, run the tests with pytest, verify the function, fix it after the failed retry"
    first = select_examples("qa_engineer", objective, retry=True)
    assert first == select_examples("qa_engineer", objective, retry=True)
    for budget in (0, 40, 120, 250, 10_000):
        chosen = select_examples("qa_engineer", objective, retry=True, budget_tokens=budget)
        assert estimate_tokens(format_examples(chosen)) <= max(budget, 0) or not chosen
        assert len(chosen) <= MAX_EXAMPLES
    assert select_examples("qa_engineer", objective, retry=True, budget_tokens=0) == []


def test_an_example_that_does_not_fit_is_left_out_not_cut():
    full = format_examples(select_examples("security_engineer", "Review the project for security problems", budget_tokens=250))
    assert full and HEADING in full
    assert select_examples("security_engineer", "Review the project for security problems", budget_tokens=60) == []


async def brief_of_backend_task(tmp_path, cfg):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Create slug.py with a function slugify.\nWRITES: a/**"), lambda m: ok())
    model = Playbook(pm=pm)
    events, result = await go(tmp_path, model, cfg)
    return model.briefs[0], events, result


async def test_the_examples_in_the_task_message_are_recorded(tmp_path):
    brief, events, result = await brief_of_backend_task(tmp_path, RunConfig())
    assert HEADING in brief and "slugify" in brief
    supplied = of_type(events, "examples_supplied")
    assert len(supplied) == 1 and supplied[0]["ids"] == ["backend-small-module"] and supplied[0]["tokens"] <= 250
    assert result["task_log"].tasks[0].examples == ["backend-small-module"]


async def test_examples_can_be_switched_off(tmp_path):
    brief, events, result = await brief_of_backend_task(tmp_path, RunConfig(examples=False))
    assert HEADING not in brief and not of_type(events, "examples_supplied")
    assert result["task_log"].tasks[0].examples == []


async def test_nothing_is_added_when_no_example_matches(tmp_path):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Rename the variable.\nWRITES: a/**"), lambda m: ok())
    model = Playbook(pm=pm)
    events, _ = await go(tmp_path, model)
    assert HEADING not in model.briefs[0] and not of_type(events, "examples_supplied")


async def test_examples_leave_room_in_the_context_window_for_the_work(tmp_path):
    """With a window this small there is no room left after the reserve, so nothing is injected."""
    cfg = RunConfig(context_tokens=1900, work_reserve_tokens=1500)
    brief, events, _ = await brief_of_backend_task(tmp_path, cfg)
    assert HEADING not in brief and not of_type(events, "examples_supplied")


@pytest.mark.parametrize("role", [r for r in specialists()])
async def test_each_specialist_is_sent_little_enough_before_any_work(tmp_path, role):
    pm = pm_steps(lambda m: todos(), lambda m: delegate(load_role(role).name, "Do it.\nWRITES: a/**"), lambda m: ok())
    model = Probe(pm=pm)
    await go(tmp_path, model)
    cost = tokens(*model.first_call["specialist"])
    assert cost <= ROLE_BUDGET_TOKENS, f"{role} is sent about {cost} tokens before any work (budget {ROLE_BUDGET_TOKENS})"
