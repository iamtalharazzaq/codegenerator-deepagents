"""A scripted chat model for demos and end-to-end checks (`ORCH_DEMO=1`): no LLM needed.

It plays every role through the real agent machinery (so tool calls, write scopes, status blocks and events are all
genuine): the Project Manager answers with a plan whose middle tasks can run side by side; each specialist writes
one file in its own area and replies with a status block. QA fails once, the planner adds a backend fix and retries
QA, which then passes (`ORCH_DEMO_SCENARIO=escalate` makes QA fail every time, so the run escalates).
"""

from __future__ import annotations

import asyncio
import json
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

ROLE_BY_NAME = {
    "Project Manager": "project_manager", "Business Analyst": "business_analyst", "Product Manager": "product_manager",
    "Solution Architect": "solution_architect", "Code Analyst": "code_analyst", "Database Engineer": "database_engineer",
    "Backend Developer": "backend_developer", "Frontend Developer": "frontend_developer", "UI/UX Designer": "ui_ux_designer",
    "QA Engineer": "qa_engineer", "DevOps Engineer": "devops_engineer",
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


def _task(key: str, role: str, objective: str, writes: list[str], depends: list[str] | None = None) -> dict[str, Any]:
    return {
        "key": key, "role": role, "objective": objective, "inputs": [], "done_condition": f"{objective} is finished and checked",
        "depends_on": depends or [], "writes": writes,
    }


def _plan_reply(text: str, tasks: list[dict[str, Any]]) -> str:
    return f"{text}\n```json\n{json.dumps(tasks, indent=2)}\n```"


class DemoModel(BaseChatModel):
    delay: float = float(os.environ.get("ORCH_DEMO_DELAY", "0.9"))
    scenario: str = os.environ.get("ORCH_DEMO_SCENARIO", "recover")
    # QA really calls `run_tests` in the sandbox and always *claims* a pass, so the orchestrator's exit-code check
    # (not the model's word) decides: the first run exits 1, later runs exit 0 (every run exits 1 when escalating).
    real_tools: bool = os.environ.get("ORCH_DEMO_SANDBOX") == "1"
    _qa_runs: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "demo"

    def bind_tools(self, tools: Any, **kwargs: Any) -> DemoModel:
        return self

    # -------------------------------------------------------------- the script

    def _answer(self, messages: list[BaseMessage]) -> AIMessage:
        system = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
        human = next((m.content for m in messages if isinstance(m, HumanMessage)), "")
        system, human = str(system), str(human)
        found = re.search(r"You are the ([A-Za-z/ ]+?)[.,\n]", system)
        role = ROLE_BY_NAME.get(found.group(1).strip(), "") if found else ""
        if role == "project_manager":
            return AIMessage(content=self._planner(human))
        return self._worker(role, messages, human)

    def _planner(self, prompt: str) -> str:
        if "three-sentence summary" in prompt:
            return "The run split the request into a design, three parallel build tasks and a test pass. QA caught a real bug once, a fix was added, and the retry passed." if self.scenario != "escalate" else "The run reached QA, which failed twice, so it stopped for a decision."
        if "The last task failed" in prompt:
            return _plan_reply(
                "QA found that expired tokens are still accepted. I am adding a backend fix first, then QA gets its second and last try.",
                [
                    _task("fix", "backend_developer", "Reject expired reset tokens", ["backend/**"]),
                    _task("qa", "qa_engineer", "Re-run the flow tests after the fix", ["tests/**"], ["fix"]),
                ],
            )
        return _plan_reply(
            "I split this into six tasks: understand the code, design it, then database, backend and frontend side by side, then test.",
            [
                _task("map", "code_analyst", "Map the existing code this change touches", ["docs/map.md"]),
                _task("design", "solution_architect", "Write the design: boundaries, data flow, endpoints", ["docs/design.md"], ["map"]),
                _task("db", "database_engineer", "Add the data model and migration", ["db/**"], ["design"]),
                _task("api", "backend_developer", "Implement the backend endpoints", ["backend/**"], ["design"]),
                _task("ui", "frontend_developer", "Build the screens and wire them to the API", ["frontend/**"], ["design"]),
                _task("qa", "qa_engineer", "Write and run the flow tests", ["tests/**"], ["db", "api", "ui"]),
            ],
        )

    def _worker(self, role: str, messages: list[BaseMessage], human: str) -> AIMessage:
        wrote = any(isinstance(m, ToolMessage) for m in messages)
        path, body = FILES.get(role, ("/docs/notes.md", "notes\n"))
        if role == "qa_engineer" and self.real_tools:
            if not wrote:
                self._qa_runs += 1
                failing = self.scenario == "escalate" or self._qa_runs == 1
                code = f"import sys; print({'1 failed' if failing else '2 passed'!r}); sys.exit({int(failing)})"
                call = {"name": "run_tests", "args": {"command": ["python", "-c", code], "toolchain": "python"},
                        "id": uuid.uuid4().hex[:12], "type": "tool_call"}
                return AIMessage(content="", tool_calls=[call])
            return AIMessage(content="Ran the tests.\n---\nstatus: pass\nreason: the tests ran\n---")
        if not wrote:
            if role == "qa_engineer":
                self._qa_runs += 1
            call = {"name": "write_file", "args": {"file_path": path, "content": body}, "id": uuid.uuid4().hex[:12], "type": "tool_call"}
            return AIMessage(content="", tool_calls=[call])
        summary = SUMMARY.get(role, "Done.")
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
