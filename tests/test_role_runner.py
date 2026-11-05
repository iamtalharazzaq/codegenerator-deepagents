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


def tool_call_message(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


async def test_traced_run_reports_tool_calls_and_results(tmp_path: Path):
    from orchestrator.role_runner import run_role_traced

    model = ScriptedModel(messages=iter([
        tool_call_message("write_file", {"file_path": "/a.md", "content": "hi"}),
        AIMessage(content="ok\n---\nstatus: pass\nreason: r\n---"),
    ]))
    seen: list[tuple[str, str]] = []
    run = await run_role_traced("product_manager", "go", model, tmp_path, on_tool=lambda k, r: seen.append((k, r.name)))
    assert seen == [("call", "write_file"), ("result", "write_file")]
    assert [c.name for c in run.calls] == ["write_file"]
    assert "status: pass" in run.text


async def test_write_scope_blocks_a_write_and_the_file_is_not_created(tmp_path: Path):
    from orchestrator.guardrails import WriteScope
    from orchestrator.role_runner import run_role_traced

    model = ScriptedModel(messages=iter([
        tool_call_message("write_file", {"file_path": "/frontend/x.js", "content": "x"}),
        AIMessage(content="done\n---\nstatus: pass\nreason: r\n---"),
    ]))
    blocks: list[tuple[str, str, str]] = []
    run = await run_role_traced(
        "backend_developer", "go", model, tmp_path,
        write_scope=WriteScope(globs=("backend/**",)), on_block=lambda t, p, r: blocks.append((t, p, r)),
    )
    assert not (tmp_path / "frontend" / "x.js").exists()
    assert blocks and blocks[0][1] == "/frontend/x.js" and "outside" in blocks[0][2]
    assert run.calls[0].error and run.calls[0].output.startswith("Blocked:")


async def test_write_inside_scope_is_allowed(tmp_path: Path):
    from orchestrator.guardrails import WriteScope
    from orchestrator.role_runner import run_role_traced

    model = ScriptedModel(messages=iter([
        tool_call_message("write_file", {"file_path": "/backend/x.py", "content": "x"}),
        AIMessage(content="done"),
    ]))
    await run_role_traced("backend_developer", "go", model, tmp_path, write_scope=WriteScope(globs=("backend/**",)))
    assert (tmp_path / "backend" / "x.py").read_text() == "x"


def test_parse_plan_reads_dependencies_writes_and_replaces():
    plan = parse_plan(
        '```json\n[{"key": "a", "role": "solution_architect", "objective": "o", "done_condition": "d"},'
        '{"key": "b", "role": "backend_developer", "objective": "o", "done_condition": "d",'
        ' "depends_on": ["a"], "writes": ["backend/**"], "replaces": "abc12345"}]\n```'
    )
    assert plan[1].depends_on == ["a"] and plan[1].writes == ["backend/**"] and plan[1].replaces == "abc12345"


def test_parse_plan_rejects_cycles_and_duplicate_keys():
    base = '{"role": "backend_developer", "objective": "o", "done_condition": "d"'
    cyc = f'```json\n[{base}, "key": "a", "depends_on": ["b"]}}, {base}, "key": "b", "depends_on": ["a"]}}]\n```'
    with pytest.raises(ValueError, match="cycle"):
        parse_plan(cyc)
    dup = f'```json\n[{base}, "key": "a"}}, {base}, "key": "a"}}]\n```'
    with pytest.raises(ValueError, match="duplicate"):
        parse_plan(dup)


def test_plan_summary_is_the_text_before_the_json():
    from orchestrator.role_runner import plan_summary

    assert plan_summary("Backend first, then QA.\n```json\n[]\n```") == "Backend first, then QA."


async def test_an_agent_that_keeps_writing_outside_its_scope_is_stopped(tmp_path: Path):
    """Seen with the real 9B model: it retried a blocked write 20+ times until the task timeout."""
    from orchestrator.guardrails import AgentStuck, WriteScope
    from orchestrator.role_runner import run_role_traced

    attempts = [tool_call_message("write_file", {"file_path": f"/x{i}.md", "content": "x"}, f"c{i}") for i in range(10)]
    model = ScriptedModel(messages=iter(attempts))
    with pytest.raises(AgentStuck, match="outside its scope 3 times"):
        await run_role_traced("backend_developer", "go", model, tmp_path, write_scope=WriteScope(globs=("greet.py",)))
    assert not list(tmp_path.glob("x*.md"))


async def test_an_agent_repeating_the_same_call_is_stopped(tmp_path: Path):
    from orchestrator.guardrails import AgentStuck
    from orchestrator.role_runner import run_role_traced

    same = [tool_call_message("read_file", {"file_path": "/nope.txt"}, f"c{i}") for i in range(10)]
    with pytest.raises(AgentStuck, match="repeated the same read_file call 4 times"):
        await run_role_traced("backend_developer", "go", ScriptedModel(messages=iter(same)), tmp_path)


async def test_a_step_budget_stops_an_endless_agent(tmp_path: Path):
    from orchestrator.role_runner import run_role_traced

    varied = [tool_call_message("read_file", {"file_path": f"/f{i}.txt"}, f"c{i}") for i in range(40)]
    with pytest.raises(Exception, match="[Rr]ecursion"):
        await run_role_traced("backend_developer", "go", ScriptedModel(messages=iter(varied)), tmp_path, max_steps=8)
