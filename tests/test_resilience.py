"""Fault tolerance with LangChain's / deepagents' own middleware: ModelRetryMiddleware (every model call),
ToolRetryMiddleware (sandbox runner briefly unreachable) and
ModelCallLimitMiddleware (a specialist that never finishes). Only the failures are scripted; the machinery is real."""

import httpx
import openai
from agent.tools.sandbox import SandboxUnavailable
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from test_agency import Playbook, delegate, go, of_type, ok, pm_steps, todos
from test_team import calls, tc

from orchestrator.config import RunConfig


class Down(BaseChatModel):
    """A model server that never answers."""

    @property
    def _llm_type(self) -> str:
        return "down"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise openai.APITimeoutError(request=httpx.Request("POST", "http://model/v1/chat/completions"))


def writer(messages):
    """A specialist that writes one file and passes."""
    if any(isinstance(m, ToolMessage) for m in messages):
        return ok("Wrote it.")
    return calls(tc("write_file", {"file_path": "/a/x.py", "content": "1"}, "w1"))


def one_task_pm():
    return pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"), lambda m: ok())


async def test_a_model_that_stays_down_stops_the_run_as_resumable(tmp_path):
    _, result = await go(tmp_path, Down(), RunConfig(max_model_retries=2, max_nudges=0))
    assert (result["status"], result["end_reason"]) == ("escalated", "model_unavailable")


class FlakySandbox:
    """The runner is unreachable for the first `fail_first` calls, then behaves."""

    def __init__(self, fail_first):
        self.fail_first, self.sessions = fail_first, 0

    async def create_session(self, workspace, services):
        self.sessions += 1
        if self.sessions <= self.fail_first:
            raise SandboxUnavailable("runner unreachable")
        return {"id": "s1", "workspace": workspace, "services": [], "previews": []}

    async def delete_session(self, sid):
        pass

    async def close(self):
        pass

    async def job(self, sid, spec):
        yield {"type": "output", "stream": "stdout", "text": "1 passed\n"}
        yield {"type": "exit", "code": 0, "timed_out": False, "oom_killed": False, "duration_s": 0.1}


def qa_specialist(messages):
    if any(isinstance(m, ToolMessage) and "exit 0" in str(m.content) for m in messages):
        return ok("Ran the tests: exit 0.")
    if any(isinstance(m, ToolMessage) and "Error" in str(m.content) for m in messages):
        return AIMessage(content="The runner failed.\n---\nstatus: fail\nreason: runner failed\n---")
    return calls(tc("run_tests", {"command": ["pytest", "-q"]}, "t1"))


async def test_a_sandbox_runner_that_is_briefly_unreachable_is_retried_and_counted_once(tmp_path):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("qa-engineer", "Test it.\nWRITES: t/**"), lambda m: ok())
    sandbox = FlakySandbox(fail_first=1)
    events, result = await go(tmp_path, Playbook(pm=pm, specialist=qa_specialist), RunConfig(max_nudges=0), sandbox_client=sandbox)
    assert sandbox.sessions == 2  # the failed call was retried by ToolRetryMiddleware
    assert len([e for e in of_type(events, "tool_call") if e["tool"] == "run_tests"]) == 1  # and the guard saw one call
    qa = result["task_log"].tasks[0]
    assert qa.evidence and any("run_tests ran 1 time(s), last exit 0" in line for line in qa.evidence)


async def test_a_sandbox_runner_that_stays_unreachable_fails_the_task_as_an_infrastructure_failure(tmp_path):
    pm = pm_steps(lambda m: todos(), lambda m: delegate("qa-engineer", "Test it.\nWRITES: t/**"), lambda m: ok())
    sandbox = FlakySandbox(fail_first=99)
    _, result = await go(tmp_path, Playbook(pm=pm, specialist=qa_specialist), RunConfig(max_nudges=0, max_tool_retries=1), sandbox_client=sandbox)
    task = result["task_log"].tasks[0]
    assert sandbox.sessions == 2 and (task.status, task.failure_kind) == ("fail", "infrastructure")


async def test_a_specialist_that_never_finishes_is_cut_off_by_the_model_call_limit(tmp_path):
    counter = {"n": 0}

    def looper(messages):
        counter["n"] += 1
        return calls(tc("ls", {"path": f"/d{counter['n']}"}, f"c{counter['n']}"))  # a different call each time: not a repeat

    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"), lambda m: ok())
    _, result = await go(tmp_path, Playbook(pm=pm, specialist=looper), RunConfig(max_nudges=0, max_model_calls_per_task=4))
    task = result["task_log"].tasks[0]
    assert task.status == "fail" and counter["n"] <= 5  # stopped by the cap, not by running on
    assert isinstance(HumanMessage(content=""), HumanMessage)  # (keeps the import used when the assertion above changes)


async def test_tool_calls_over_the_cap_are_refused_by_toolcalllimitmiddleware(tmp_path):
    seen = []

    def looper(messages):
        seen.extend(str(m.content) for m in messages if isinstance(m, ToolMessage))
        n = sum(isinstance(m, ToolMessage) for m in messages) + 1
        return calls(tc("ls", {"path": f"/d{n}"}, f"c{n}")) if n <= 6 else ok("Gave up.")

    pm = pm_steps(lambda m: todos(), lambda m: delegate("backend-developer", "Make a.\nWRITES: a/**"), lambda m: ok())
    await go(tmp_path, Playbook(pm=pm, specialist=looper), RunConfig(max_nudges=0, max_tool_calls_per_task=3))
    assert any("limit" in text.lower() for text in seen)  # the 4th call was answered with the limit, not executed


def test_a_chat_reply_retries_with_langchains_with_retry():
    import asyncio

    from orchestrator import chat as chats

    calls_made = []

    class Flaky(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "flaky"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # pragma: no cover
            raise NotImplementedError

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            calls_made.append(1)
            if len(calls_made) < 3:
                raise openai.APITimeoutError(request=httpx.Request("POST", "http://m/v1"))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="hello"))])

    chat = {"messages": [{"role": "user", "text": "hi"}]}
    assert asyncio.run(chats.ask_model(Flaky(), chat, plan=False, wait_s=0.0)) == "hello" and len(calls_made) == 3
