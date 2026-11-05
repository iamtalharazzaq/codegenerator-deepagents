"""Run limits and switches. One frozen object per run, so every limit lives in one place."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunConfig:
    # How many delegations may run at once. 1 until the model server has more slots (codewright's
    # `max_parallel_llm_jobs`); the Project Manager may ask for several, the rest wait their turn.
    concurrency: int = 1
    # Safety limits. They are not a loop: the Project Manager decides what to do next, these only stop a runaway.
    max_total_dispatches: int = 20  # delegations in one run
    run_timeout_s: float = 3600.0
    task_timeout_s: float = 600.0
    max_tool_calls_per_task: int = 100  # a specialist stuck in a loop is stopped well before the task timeout
    max_pm_steps: int = 400  # LangGraph steps for the whole team (the model and tool steps count separately)
    # Per-task write budgets (guardrails).
    max_file_bytes: int = 200_000
    max_files_per_task: int = 30
    # If the Project Manager ends its turn without having delegated anything (a small model may "finish" the work in
    # words), ask it once to delegate. It is a nudge, not a loop: the Project Manager still decides everything.
    max_nudges: int = 1
    # A deep agent plans before it acts. If the Project Manager tries to delegate before it has written a to-do list with
    # `write_todos`, the delegation is refused and it is told to plan first (at most `max_plan_refusals` times, then it
    # is let through with a warning). The API and the CLI turn this on.
    require_plan: bool = False
    max_plan_refusals: int = 2
    # Before the zip is built, pause and ask the person whether anything should change. If so, the Project Manager gets
    # their note, does the extra work, and the person is asked again (at most this many times).
    final_review: bool = False  # the API turns this on by default
    max_review_rounds: int = 5
    # Hold the first delegation until the person approves the plan (the API turns this on by default).
    plan_approval: bool = False
