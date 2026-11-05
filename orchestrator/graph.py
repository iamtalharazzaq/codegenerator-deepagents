"""The orchestration graph: plan -> dispatch -> observe -> (dispatch | replan | escalate | done).

- `plan` asks the Project Manager role for a JSON task list (on a replan, for the *remaining* work, with
  the last failure's summary in the prompt).
- `dispatch` runs the first open task's role agent once (`run_role`, no nested sub-agents) and writes its
  reply to `runs/<run_id>/<task.id>.md`.
- `observe` parses that artifact's status block (`parse_status`, never trusting prose) and marks the task
  `pass`, `fail` (-> replan) or, on its 2nd failure, `escalated` (terminal: no 3rd attempt, no 3rd plan).

Retry accounting: a task's `attempt` counts dispatches of that task. Replanning keeps a still-open task's
`id` and `attempt` when the new plan re-proposes it — exactly (same role+objective), or, for the task that
just failed, as a revision of it (same role, reworded objective). Without the second rule the attempt cap
could be dodged by the planner rewording the objective each time.
"""

from __future__ import annotations

import uuid
from typing import Literal, NotRequired, TypedDict

from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator.role_runner import PlannedTask, parse_plan, run_role
from orchestrator.runs import read_artifact, run_dir, write_artifact
from orchestrator.sandbox_tools import sandbox_tools_for
from orchestrator.status_block import parse_status
from orchestrator.task import Task, TaskLog, save_task_log

MAX_ATTEMPTS = 2
TASK_LOG_FILE = "task_log.json"
OPEN_STATUSES = ("pending", "fail")

ROSTER = """\
- project_manager: plans the work and breaks it into tasks
- business_analyst: clarifies requirements and acceptance criteria
- product_manager: writes user stories and priorities
- solution_architect: designs the system and its interfaces
- code_analyst: reads and explains the existing code
- database_engineer: designs schemas and migrations
- backend_developer: implements server-side code
- frontend_developer: implements client-side code
- ui_ux_designer: designs screens and interactions
- qa_engineer: writes and runs tests (has a run_tests sandbox tool)
- devops_engineer: builds and packages the project (has a run_build sandbox tool)"""

STATUS_BLOCK_FORMAT = "---\nstatus: pass|fail\nreason: <one line>\n---"


class OrchestratorState(TypedDict):
    request: str
    workspace: Workspace
    run_id: str
    model: BaseChatModel
    sandbox_client: NotRequired[SandboxClient | None]
    task_log: TaskLog
    last_failure: str | None
    # Id of the task most recently dispatched; observe/route read it. Set by dispatch_node.
    current_task_id: NotRequired[str | None]


def _persist(state: OrchestratorState) -> None:
    save_task_log(state["task_log"], run_dir(state["workspace"], state["run_id"]) / TASK_LOG_FILE)


def _current_task(state: OrchestratorState) -> Task:
    task_id = state.get("current_task_id")
    for task in state["task_log"].tasks:
        if task.id == task_id:
            return task
    raise LookupError(f"no task with id {task_id!r} in the task log")


def _plan_prompt(state: OrchestratorState) -> str:
    parts = [
        f"Request:\n{state['request']}",
        f"Roles you can assign tasks to:\n{ROSTER}",
    ]
    done = [t for t in state["task_log"].tasks if t.status == "pass"]
    if done:
        parts.append("Already done (do not re-plan these):\n" + "\n".join(f"- {t.role}: {t.objective}" for t in done))
    if state["last_failure"]:
        parts.append(
            f"The last task failed:\n{state['last_failure']}\n\n"
            "Give a revised plan for the REMAINING work only. To retry the failed task, keep its role "
            "(you may reword its objective); it will count as that task's next attempt."
        )
    parts.append(
        "Reply with a fenced ```json block holding a list of tasks, each "
        '{"role": ..., "objective": ..., "inputs": [...], "done_condition": ...}.'
    )
    return "\n\n".join(parts)


def _merge_plan(log: TaskLog, planned: list[PlannedTask]) -> list[Task]:
    """Closed tasks stay; the new plan replaces every open one. An open task the plan re-proposes keeps
    its id and attempt count (exact role+objective match first; then the failed task matches the first
    unclaimed planned task with its role). Open tasks the plan drops are superseded and removed."""
    closed = [t for t in log.tasks if t.status not in OPEN_STATUSES]
    open_tasks = [t for t in log.tasks if t.status in OPEN_STATUSES]
    claimed: dict[int, Task] = {}  # index in `planned` -> existing task it continues
    used: set[str] = set()

    for i, p in enumerate(planned):
        for t in open_tasks:
            if t.id not in used and t.role == p.role and t.objective == p.objective:
                claimed[i] = t
                used.add(t.id)
                break
    for t in open_tasks:
        if t.status != "fail" or t.id in used:
            continue
        for i, p in enumerate(planned):
            if i not in claimed and p.role == t.role:
                claimed[i] = t
                used.add(t.id)
                break

    merged: list[Task] = []
    for i, p in enumerate(planned):
        existing = claimed.get(i)
        if existing is not None:
            existing.objective = p.objective
            existing.inputs = tuple(p.inputs)
            existing.done_condition = p.done_condition
            merged.append(existing)
        else:
            merged.append(
                Task(
                    id=uuid.uuid4().hex[:8],
                    role=p.role,
                    objective=p.objective,
                    inputs=tuple(p.inputs),
                    done_condition=p.done_condition,
                    status="pending",
                )
            )
    return closed + merged


async def plan_node(state: OrchestratorState) -> dict:
    reply = await run_role("project_manager", _plan_prompt(state), state["model"], state["workspace"].work, extra_tools=())
    log = state["task_log"]
    log.tasks = _merge_plan(log, parse_plan(reply))
    _persist(state)
    return {"task_log": log, "last_failure": None}


async def dispatch_node(state: OrchestratorState) -> dict:
    log = state["task_log"]
    task = next(t for t in log.tasks if t.status in OPEN_STATUSES)
    filename = f"{task.id}.md"
    objective_text = (
        f"{task.objective}\n\n"
        f"Inputs: {', '.join(task.inputs) or 'none'}\n"
        f"Done when: {task.done_condition}\n\n"
        f"Your reply is saved as the result artifact `{filename}`. End it with exactly this status block "
        f"(status is pass only if the done condition is met):\n{STATUS_BLOCK_FORMAT}"
    )
    client = state.get("sandbox_client")
    tools = sandbox_tools_for(task.role, client) if client is not None else []
    reply = await run_role(task.role, objective_text, state["model"], state["workspace"].work, extra_tools=tools)
    write_artifact(state["workspace"], state["run_id"], filename, reply)
    task.status = "in_progress"
    task.attempt += 1
    _persist(state)
    return {"task_log": log, "current_task_id": task.id}


async def observe_node(state: OrchestratorState) -> dict:
    task = _current_task(state)
    artifact = read_artifact(state["workspace"], state["run_id"], f"{task.id}.md")
    result = parse_status(artifact)
    last_failure: str | None = None
    if result.status == "pass":
        task.status = "pass"
    elif task.attempt >= MAX_ATTEMPTS:
        task.status = "escalated"
    else:
        task.status = "fail"
        last_failure = (
            f"role: {task.role}\nobjective: {task.objective}\ndone_condition: {task.done_condition}\n"
            f"attempt: {task.attempt}\nreason: {result.reason}\nartifact:\n{artifact}"
        )
    _persist(state)
    return {"task_log": state["task_log"], "last_failure": last_failure}


def route_after_observe(state: OrchestratorState) -> Literal["dispatch", "plan", "escalate", "done"]:
    task = _current_task(state)
    if task.status == "escalated":
        return "escalate"
    if task.status == "fail":
        return "plan"
    if task.status == "pass":
        remaining = any(t.status in OPEN_STATUSES for t in state["task_log"].tasks)
        return "dispatch" if remaining else "done"
    raise ValueError(f"unexpected status {task.status!r} after observe")


async def escalate_node(state: OrchestratorState) -> dict:
    """Terminal: a task failed its last allowed attempt. The task log already records it as escalated."""
    return {}


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(OrchestratorState)
    graph.add_node("plan", plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("observe", observe_node)
    graph.add_node("escalate", escalate_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "observe")
    graph.add_conditional_edges(
        "observe",
        route_after_observe,
        {"dispatch": "dispatch", "plan": "plan", "escalate": "escalate", "done": END},
    )
    graph.add_edge("escalate", END)
    return graph.compile()
