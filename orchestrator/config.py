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
    # Hold the first delegation until the person approves the plan (the API turns this on by default).
    plan_approval: bool = False
