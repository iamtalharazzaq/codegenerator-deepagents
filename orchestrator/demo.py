"""A scripted chat model for demos and end-to-end checks (`ORCH_DEMO=1`): no LLM needed.

It plays every role through the real deepagents machinery (so the to-do list, the `task` delegations, tool calls,
write scopes and status blocks are all genuine). The Project Manager writes a to-do list, delegates to the code
analyst and architect, then to the database, backend and frontend specialists in one turn (they run side by side),
then to QA. QA fails once; the Project Manager updates its to-do list, delegates a backend fix, and QA runs again
and passes. `ORCH_DEMO_SCENARIO=escalate` makes QA fail every time, so the Project Manager ends with `status: fail`.
`ORCH_DEMO_SANDBOX=1` makes QA really run its tests in the sandbox (the verdict follows the real exit code).
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from orchestrator.status_block import parse_status

ROLE_BY_NAME = {
    "Project Manager": "project_manager", "Business Analyst": "business_analyst", "Product Manager": "product_manager",
    "Solution Architect": "solution_architect", "Code Analyst": "code_analyst", "Database Engineer": "database_engineer",
    "Backend Developer": "backend_developer", "Frontend Developer": "frontend_developer", "UI/UX Designer": "ui_ux_designer",
    "QA Engineer": "qa_engineer", "DevOps Engineer": "devops_engineer",
}
SUBAGENT_NAME = {
    "code_analyst": "code-analyst", "solution_architect": "solution-architect", "database_engineer": "database-engineer",
    "backend_developer": "backend-developer", "frontend_developer": "frontend-developer", "qa_engineer": "qa-engineer",
}
FILES = {
    "code_analyst": ("/docs/map.md", "# Code map\n\nEntry points and the modules this change touches.\n"),
    "solution_architect": ("/docs/design.md", "# Design\n\nA small service boundary, one new table, two endpoints, one screen.\n"),
    "database_engineer": ("/db/migrations/001_create_tables.sql", "CREATE TABLE reset_tokens (token_hash TEXT PRIMARY KEY, expires_at TIMESTAMP);\n"),
    "backend_developer": ("/backend/app.py", "def request_reset(email):\n    return {'sent': True}\n\n\ndef confirm_reset(token, password):\n    return {'ok': True}\n"),
    "frontend_developer": ("/frontend/index.html", "<form><input name=\"email\"><button>Send reset link</button></form>\n"),
    "qa_engineer": ("/tests/test_flow.py", "def test_expired_token_is_rejected():\n    assert True\n"),
}
SUMMARY = {
    "code_analyst": "Mapped the auth and session code the change touches.",
    "solution_architect": "Wrote the design: boundaries, data flow and the two new endpoints.",
    "database_engineer": "Added the migration for the token table.",
    "backend_developer": "Implemented the request and confirm endpoints.",
    "frontend_developer": "Built the forgot-password screen and wired it to the API.",
    "qa_engineer": "Wrote and ran the flow tests.",
}


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "args": args, "id": uuid.uuid4().hex[:12], "type": "tool_call"}


def _task(role: str, description: str, writes: str) -> dict[str, Any]:
    return _call("task", {"description": f"{description}\nWRITES: {writes}", "subagent_type": SUBAGENT_NAME[role]})


def _todos(items: list[tuple[str, str]]) -> dict[str, Any]:
    return _call("write_todos", {"todos": [{"content": c, "status": s} for c, s in items]})


FIRST_TODOS = [
    ("Code Analyst: map the code this change touches", "in_progress"),
    ("Solution Architect: write the design", "pending"),
    ("Database, Backend and Frontend: build in parallel", "pending"),
    ("QA Engineer: write and run the flow tests", "pending"),
]
FIX_TODOS = [
    ("Code Analyst: map the code this change touches", "completed"),
    ("Solution Architect: write the design", "completed"),
    ("Database, Backend and Frontend: build in parallel", "completed"),
    ("Backend Developer: reject expired reset tokens (QA found it)", "in_progress"),
    ("QA Engineer: re-run the flow tests", "pending"),
]


class DemoModel(BaseChatModel):
    delay: float = float(os.environ.get("ORCH_DEMO_DELAY", "0.9"))
    scenario: str = os.environ.get("ORCH_DEMO_SCENARIO", "recover")
    # QA really calls `run_tests` in the sandbox; its verdict follows the real exit code (first run exits 1, later
    # runs exit 0; every run exits 1 when escalating).
    real_tools: bool = os.environ.get("ORCH_DEMO_SANDBOX") == "1"
    _qa_runs: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "demo"

    def bind_tools(self, tools: Any, **kwargs: Any) -> DemoModel:
        return self

    # -------------------------------------------------------------- the script

    def _answer(self, messages: list[BaseMessage]) -> AIMessage:
        system = str(next((m.content for m in messages if isinstance(m, SystemMessage)), ""))
        found = re.search(r"You are the ([A-Za-z/ ]+?)[.,\n]", system)
        role = ROLE_BY_NAME.get(found.group(1).strip(), "") if found else ""
        if role == "project_manager":
            return self._project_manager(messages)
        human = str(next((m.content for m in messages if isinstance(m, HumanMessage)), ""))
        return self._specialist(role, messages, human)

    def _project_manager(self, messages: list[BaseMessage]) -> AIMessage:
        wrote_todos = 0
        asked: dict[str, str] = {}
        results: list[tuple[str, bool]] = []  # (specialist, passed) in the order the results arrived
        for m in messages:
            if isinstance(m, AIMessage):
                for c in m.tool_calls:
                    if c["name"] == "write_todos":
                        wrote_todos += 1
                    if c["name"] == "task":
                        asked[c["id"] or ""] = c["args"]["subagent_type"]
            elif isinstance(m, ToolMessage) and m.tool_call_id in asked:
                results.append((asked[m.tool_call_id], parse_status(str(m.content)).status == "pass"))

        def count(name: str) -> int:
            return sum(1 for n, _ in results if n == name)

        if wrote_todos == 0:
            return AIMessage(content="", tool_calls=[_todos(FIRST_TODOS)])  # type: ignore[list-item]
        if count("code-analyst") == 0:
            return AIMessage(content="", tool_calls=[_task("code_analyst", "Map the existing code this change touches.", "docs/map.md")])  # type: ignore[list-item]
        if count("solution-architect") == 0:
            return AIMessage(content="", tool_calls=[_task("solution_architect", "Write the design: boundaries, data flow, endpoints.", "docs/design.md")])  # type: ignore[list-item]
        if count("database-engineer") == 0:
            return AIMessage(content="", tool_calls=[  # type: ignore[list-item]
                _task("database_engineer", "Add the data model and migration.", "db/**"),
                _task("backend_developer", "Implement the backend endpoints.", "backend/**"),
                _task("frontend_developer", "Build the screens and wire them to the API.", "frontend/**"),
            ])
        if count("qa-engineer") == 0:
            return AIMessage(content="", tool_calls=[_task("qa_engineer", "Write and run the flow tests.", "tests/**")])  # type: ignore[list-item]
        qa_ok = [ok for n, ok in results if n == "qa-engineer"][-1]
        if qa_ok:
            return AIMessage(content=(
                "The request was split into a design, three parallel build tasks and a test pass. "
                "QA caught a real bug once, a backend fix was added, and the retry passed. Everything is delivered."
                "\n---\nstatus: pass\nreason: all tasks passed\n---"))
        if count("qa-engineer") >= 2:
            return AIMessage(content=(
                "QA failed twice, so I am stopping here for a decision instead of trying a third time."
                "\n---\nstatus: fail\nreason: QA failed twice\n---"))
        if wrote_todos == 1:
            return AIMessage(content="", tool_calls=[_todos(FIX_TODOS)])  # type: ignore[list-item]
        if count("backend-developer") == 1:
            return AIMessage(
                content="QA found that expired tokens are still accepted. Adding a backend fix first.",
                tool_calls=[_task("backend_developer", "Reject expired reset tokens.", "backend/**")],  # type: ignore[list-item]
            )
        return AIMessage(content="", tool_calls=[_task("qa_engineer", "Re-run the flow tests after the fix.", "tests/**")])  # type: ignore[list-item]

    def _specialist(self, role: str, messages: list[BaseMessage], human: str) -> AIMessage:
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        path, body = FILES.get(role, ("/docs/notes.md", "notes\n"))
        summary = SUMMARY.get(role, "Done.")
        if role == "qa_engineer" and self.real_tools:
            if not tool_results:
                self._qa_runs += 1
                failing = self.scenario == "escalate" or self._qa_runs == 1
                code = f"import sys; print({'1 failed' if failing else '2 passed'!r}); sys.exit({int(failing)})"
                return AIMessage(content="", tool_calls=[_call("run_tests", {"command": ["python", "-c", code], "toolchain": "python"})])  # type: ignore[list-item]
            ok = str(tool_results[-1].content).startswith("exit 0")
            word = "pass" if ok else "fail"
            return AIMessage(content=f"Ran the tests.\n---\nstatus: {word}\nreason: {'tests passed' if ok else 'tests failed'}\n---")
        if not tool_results:
            if role == "qa_engineer":
                self._qa_runs += 1
            return AIMessage(content="", tool_calls=[_call("write_file", {"file_path": path, "content": body})])  # type: ignore[list-item]
        if role == "qa_engineer" and (self.scenario == "escalate" or self._qa_runs == 1):
            return AIMessage(content=f"{summary}\n\ntest_expired_token_rejected failed.\n---\nstatus: fail\nreason: test_expired_token_rejected failed\n---")
        return AIMessage(content=f"{summary}\n---\nstatus: pass\nreason: {summary}\n---")

    # -------------------------------------------------------------- BaseChatModel plumbing

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._answer(messages))])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                         run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        await asyncio.sleep(self.delay)
        return self._generate(messages, stop)
