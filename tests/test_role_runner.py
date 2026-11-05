from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from orchestrator.role_runner import PlannedTask, parse_plan, run_role


class ScriptedModel(GenericFakeChatModel):
    """`GenericFakeChatModel` doesn't implement `bind_tools` (it raises `NotImplementedError`),
    but `create_deep_agent` always binds tools to the model. Mirrors codewright's
    `agent/tests/test_team.py::ScriptedModel`."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def test_parse_plan_extracts_fenced_json():
    text = (
        "Here's the plan:\n```json\n"
        '[{"role": "product_manager", "objective": "write stories", '
        '"inputs": [], "done_condition": "stories.md exists"}]\n```\n'
    )
    plan = parse_plan(text)
    assert plan == [
        PlannedTask(role="product_manager", objective="write stories", inputs=[], done_condition="stories.md exists")
    ]


def test_parse_plan_rejects_unknown_role():
    text = '```json\n[{"role": "ceo", "objective": "x", "done_condition": "y"}]\n```'
    with pytest.raises(ValueError, match="role"):
        parse_plan(text)


def test_parse_plan_rejects_missing_json_block():
    with pytest.raises(ValueError, match="json"):
        parse_plan("I didn't give you a plan.")


async def test_run_role_writes_a_file_and_returns_final_message(tmp_path: Path):
    model = ScriptedModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"file_path": "/stories.md", "content": "# Stories\n"},
                            "id": "c1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Wrote stories.md.\n---\nstatus: pass\nreason: 1 story\n---"),
            ]
        )
    )
    reply = await run_role("product_manager", "write one user story", model, tmp_path)
    assert (tmp_path / "stories.md").read_text() == "# Stories\n"
    assert "status: pass" in reply
