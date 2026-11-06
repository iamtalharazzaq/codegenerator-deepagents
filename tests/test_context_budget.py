"""The model's context window is small (4096 tokens in config/models.yaml). What it is sent before any work starts,
and what a run adds to the Project Manager's history, is held to a budget so it cannot creep back up unnoticed."""

import json

from langchain_core.messages import SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field
from test_agency import Playbook, delegate, go, ok, pm_steps, todos

from orchestrator.config import RunConfig
from orchestrator.lean import first_sentence, lean
from orchestrator.team import trim_reply

# Tokens are estimated as characters / 4. Measured when this was written: Project Manager ~1,350, specialist ~750.
# The specialist prompts were then rewritten (inputs, outputs, boundaries, escalation): backend-developer is now ~970;
# test_examples.py holds every role to its own limit.
PM_BUDGET_TOKENS = 1500
SPECIALIST_BUDGET_TOKENS = 1000
WINDOW_TOKENS = 4096


class Probe(Playbook):
    """Records the system prompt and the exact tools (as the model receives them) of its first call per agent."""

    bound: list = Field(default_factory=list)
    first_call: dict = Field(default_factory=dict)

    def bind_tools(self, tools, **kwargs):
        self.bound.append(tools)
        return self

    async def _agenerate(self, messages, *args, **kwargs):
        system = str(next(m.content for m in messages if isinstance(m, SystemMessage)))
        who = "pm" if "You are the Project Manager" in system else "specialist"
        self.first_call.setdefault(who, (system, self.bound[-1]))
        return await super()._agenerate(messages, *args, **kwargs)


def tokens(system: str, tools: list) -> int:
    payload = sum(len(json.dumps(convert_to_openai_tool(t))) for t in tools)
    return (len(system) + payload) // 4


async def test_what_each_agent_is_sent_before_any_work_stays_inside_its_budget(tmp_path):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"), lambda m: ok())
    model = Probe(pm=pm)
    await go(tmp_path, model)
    pm_cost = tokens(*model.first_call["pm"])
    specialist_cost = tokens(*model.first_call["specialist"])
    assert pm_cost <= PM_BUDGET_TOKENS, f"the Project Manager is sent about {pm_cost} tokens before any work"
    assert specialist_cost <= SPECIALIST_BUDGET_TOKENS, f"a specialist is sent about {specialist_cost} tokens before any work"
    assert pm_cost < WINDOW_TOKENS * 0.4 and specialist_cost < WINDOW_TOKENS * 0.25
    # the lean text still tells the model what it needs: who it can ask, and how
    pm_tools = {t.name: t for t in model.first_call["pm"][1]}
    assert set(pm_tools) == {"ls", "read_file", "task", "write_todos", "get_agent_capabilities"}
    assert "backend-developer" in pm_tools["task"].description and "security-engineer" in pm_tools["task"].description
    assert "general-purpose" not in pm_tools["task"].description  # the unusable sub-agent is not advertised


def test_lean_tools_keep_argument_names_and_types_but_not_their_prose():
    from langchain_core.tools import tool

    @tool
    def read_file(file_path: str, offset: int = 0, limit: int = 100) -> str:
        """Reads a file from the filesystem. Assume any path the user provides is valid. Usage: lots of prose."""
        return ""

    short = lean(read_file)
    schema = convert_to_openai_tool(short)["function"]
    assert short.description == "Reads a file from the filesystem."
    assert set(schema["parameters"]["properties"]) == {"file_path", "offset", "limit"}
    assert schema["parameters"]["required"] == ["file_path"]
    assert "description" not in json.dumps(schema["parameters"]) and "title" not in json.dumps(schema["parameters"])
    assert first_sentence("List things.\n  More text. Even more.") == "List things."


def test_a_long_reply_is_cut_for_the_project_manager_but_its_status_block_survives():
    body = "word " * 2000
    reply = f"{body}\n---\nstatus: fail\nreason: it broke\n---"
    cut = trim_reply(reply, 1200, "ab12cd34.md")
    assert len(cut) < 1300 and "full reply in ab12cd34.md" in cut
    assert cut.rstrip().endswith("---\nstatus: fail\nreason: it broke\n---")
    short = "Did it.\n---\nstatus: pass\nreason: ok\n---"
    assert trim_reply(short, 1200, "x.md") == short


async def test_the_project_manager_reads_the_cut_reply_and_the_full_one_stays_on_disk(tmp_path):
    def chatty(messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content="blah " * 800 + "\n---\nstatus: pass\nreason: ok\n---")

    pm = pm_steps(lambda m: todos(), lambda m: delegate("technical-writer", "Write docs."), lambda m: ok())
    model = Playbook(pm=pm, specialist=chatty)
    _, result = await go(tmp_path, model, RunConfig(max_reply_chars=600))
    read = next(s for s in model.pm_saw if "blah" in s)
    assert len(read) < 1000 and "full reply in" in read and "status: pass" in read
    task = result["task_log"].tasks[0]
    assert len((tmp_path / "p1" / "runs" / "r1" / f"{task.id}.md").read_text()) > 4000

