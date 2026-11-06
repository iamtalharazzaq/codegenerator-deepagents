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
    # Tries per piece of work (the first attempt plus retries, by the same or another specialist). A failure that was
    # the infrastructure's fault (timeout, crash) is retried after `retry_backoff_s` * 2^(retries so far) seconds.
    max_attempts: int = 3
    retry_backoff_s: float = 0.0  # the API sets a real pause
    # The context window is small, and every specialist reply stays in the Project Manager's history for the rest of
    # the run. A longer reply is cut to this size when it is passed on (the full text is saved as the task's artifact,
    # and its status block is always kept).
    max_reply_chars: int = 1200
    # Per-task write budgets (guardrails).
    max_file_bytes: int = 200_000
    max_files_per_task: int = 30
    # If the Project Manager ends its turn without having delegated anything (a small model may "finish" the work in
    # words), ask it once to delegate. It is a nudge, not a loop: the Project Manager still decides everything.
    max_nudges: int = 1
    # Retry loop. When the Project Manager ends its turn while a task has failed and still has tries left, code sends it
    # the failure (reason and evidence) and asks it to fix that work: a retry of the same task with a changed instruction,
    # or another specialist. At most this many such rounds per turn; each task still has at most `max_attempts` tries.
    # The API and the CLI turn this on.
    max_fix_rounds: int = 0
    # The model server can be slow or briefly gone (a timeout, a dropped connection). The Project Manager's own model call
    # is tried again this many times, waiting `model_retry_wait_s` * 2^n seconds (at most 30) between tries. If the model
    # still does not answer, the run stops as resumable (`model_unavailable`) instead of failing.
    max_model_retries: int = 5
    model_retry_wait_s: float = 0.0  # the API sets a real pause
    # A specialist that keeps calling the model without finishing is cut off after this many model calls (LangChain's
    # ModelCallLimitMiddleware); a sandbox call that fails because the runner is unreachable is retried this many times.
    max_model_calls_per_task: int = 40
    max_tool_retries: int = 2
    # Few-shot examples (see examples.py): at most `example_tokens` of them go into a task message, and only while the
    # whole prompt (system prompt, tools, task, examples) still leaves `work_reserve_tokens` of the model's
    # `context_tokens` for reading and writing files.
    examples: bool = True
    example_tokens: int = 250
    context_tokens: int = 4096
    work_reserve_tokens: int = 1500
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
    # The person's note on a plan may be a question. If the Project Manager answers in words only, it is asked (at most
    # this many times) to answer and show a plan again, so the run does not end with nobody having approved anything.
    max_plan_replies: int = 5
