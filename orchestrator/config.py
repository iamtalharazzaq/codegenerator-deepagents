"""Run limits and switches. One frozen object per run, so every limit lives in one place."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunConfig:
    # Scheduling: how many tasks may run at once. 1 until the model server has more slots
    # (codewright's `max_parallel_llm_jobs`); sandbox runs overlap even at 1.
    concurrency: int = 1
    # Loop limits (first one reached ends the run).
    max_attempts: int = 2  # per task, counted across roles
    max_total_dispatches: int = 20
    max_replans: int = 3
    max_plan_attempts: int = 2  # unparseable/invalid plans in a row
    run_timeout_s: float = 3600.0
    task_timeout_s: float = 600.0
    # Per-task write budgets (guardrails).
    max_file_bytes: int = 200_000
    max_files_per_task: int = 30
    # Switches.
    plan_approval: bool = False  # the API turns this on by default
    report_summary: bool = False  # ask the Project Manager for a short summary paragraph in report.md
    # Failure text fed back to the planner is capped: the model's context is small (4096 tokens).
    max_failure_chars: int = 1500
