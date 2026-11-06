"""Talk first: a conversation with the Project Manager before any run, saved, resumable, and turned into a run on request."""

import httpx
import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from test_demo_and_server import client_for, make_app, wait_done

from orchestrator import chat as chats
from orchestrator.server import Settings, create_app


async def test_a_conversation_is_saved_and_can_be_opened_again(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        chat = (await c.post("/api/chats")).json()
        said = (await c.post(f"/api/chats/{chat['id']}/messages", json={"text": "I want a small tool to convert units"})).json()
        assert [m["role"] for m in said["messages"]] == ["user", "assistant"]
        assert said["title"] == "I want a small tool to convert units"
        again = (await c.get(f"/api/chats/{chat['id']}")).json()
        assert again["messages"] == said["messages"]
        assert [r["id"] for r in (await c.get("/api/chats")).json()] == [chat["id"]]
        assert (await c.get("/api/chats/deadbeef")).status_code == 404
        assert (await c.get("/api/chats/..%2Fx")).status_code in (404, 422)


async def test_a_run_needs_a_plan_first_and_then_starts_from_what_was_agreed(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        chat = (await c.post("/api/chats")).json()
        cid = chat["id"]
        assert (await c.post(f"/api/chats/{cid}/plan")).status_code == 409  # nothing said yet
        await c.post(f"/api/chats/{cid}/messages", json={"text": "A tool that converts km to miles"})
        assert (await c.post(f"/api/chats/{cid}/build", json={})).status_code == 409  # no plan shown yet
        planned = (await c.post(f"/api/chats/{cid}/plan")).json()
        assert planned["messages"][-1]["kind"] == "plan"
        started = await c.post(f"/api/chats/{cid}/build", json={"plan_approval": False, "final_review": False})
        assert started.status_code == 201
        info = await wait_done(c, started.json()["run_id"])
        assert "A tool that converts km to miles" in info["meta"]["request"] and "The plan they were shown" in info["meta"]["request"]
        saved = (await c.get(f"/api/chats/{cid}")).json()
        assert saved["project"] == started.json()["project"] and saved["run_ids"] == [started.json()["run_id"]]
        # the next build from the same conversation continues the same project
        again = await c.post(f"/api/chats/{cid}/build", json={"plan_approval": False, "final_review": False})
        assert again.json()["project"] == started.json()["project"]
        await wait_done(c, again.json()["run_id"])


class Spy(BaseChatModel):
    """Records what the model was sent; replies with a fixed text (or fails with a timeout)."""

    reply: str = "ok"
    fail: bool = False
    sent: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.sent.append(list(messages))
        if self.fail:
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://m/v1"))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


def real_app(tmp_path, model):
    return create_app(Settings(workspaces_root=tmp_path), model_factory=lambda: model, sandbox_factory=lambda: None)


async def test_the_model_is_told_the_team_and_the_conversation_and_thinking_text_is_dropped(tmp_path):
    model = Spy(reply="<think>hmm</think>Two questions: who uses it?", sent=[])
    async with client_for(real_app(tmp_path, model)) as c:
        cid = (await c.post("/api/chats")).json()["id"]
        reply = (await c.post(f"/api/chats/{cid}/messages", json={"text": "Make a calculator"})).json()["messages"][-1]
        assert reply["text"] == "Two questions: who uses it?"
        system, human = model.sent[0][0], model.sent[0][-1]
        assert isinstance(system, SystemMessage) and "BEFORE any work starts" in system.content and "backend-developer" in system.content
        assert isinstance(human, HumanMessage) and human.content == "Make a calculator"
        await c.post(f"/api/chats/{cid}/plan")
        assert "Give the plan now" in model.sent[-1][-1].content  # the plan instruction is sent but not saved
        assert all("Give the plan now" not in m["text"] for m in (await c.get(f"/api/chats/{cid}")).json()["messages"])


async def test_when_the_model_is_away_the_message_is_kept_and_the_person_can_send_again(tmp_path, monkeypatch):
    monkeypatch.setattr(chats, "RETRY_WAIT_S", 0.0)
    model = Spy(fail=True, sent=[])
    async with client_for(real_app(tmp_path, model)) as c:
        cid = (await c.post("/api/chats")).json()["id"]
        r = await c.post(f"/api/chats/{cid}/messages", json={"text": "Make a calculator"})
        assert r.status_code == 503 and "Your message is saved" in r.json()["detail"]
        assert len(model.sent) == chats.MODEL_TRIES  # tried again before giving up
        assert [m["role"] for m in (await c.get(f"/api/chats/{cid}")).json()["messages"]] == ["user"]


def test_only_the_newest_messages_that_fit_are_sent_but_the_first_is_always_kept():
    chat = {"messages": [{"role": "user", "text": "THE PROBLEM"}] + [{"role": "assistant" if i % 2 else "user", "text": "x" * 900} for i in range(20)]}
    sent = chats.history(chat)
    assert sent[0].content == "THE PROBLEM" and sum(len(m.content) for m in sent) <= chats.HISTORY_CHARS + 900 + len("THE PROBLEM")
    assert len(sent) < len(chat["messages"])


def test_the_run_request_holds_what_the_person_said_and_the_last_plan_within_the_limit():
    chat = {"project": "p1", "messages": [{"role": "user", "text": f"point {i} " + "y" * 800} for i in range(10)] + [
        {"role": "assistant", "text": "old plan", "kind": "plan"}, {"role": "assistant", "text": "NEW PLAN " + "z" * 3000, "kind": "plan"}]}
    brief = chats.brief_for_run(chat)
    assert brief.startswith("point 6") and "point 9" in brief and "point 6" in brief and "point 5" not in brief and "NEW PLAN" in brief and "old plan" not in brief
    assert "continues earlier work" in brief and len(brief) <= chats.BRIEF_CHARS


async def test_the_first_message_can_ask_for_the_plan_in_key_points_and_a_chat_can_continue_a_project(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        first = await c.post("/api/runs", json={"request": "Make a calculator", "plan_approval": False, "final_review": False})
        await wait_done(c, first.json()["run_id"])
        project = first.json()["project"]
        chat = (await c.post("/api/chats", json={"project": project})).json()
        assert chat["project"] == project
        said = (await c.post(f"/api/chats/{chat['id']}/messages", json={"text": "Add a history feature", "plan": True})).json()
        assert [m["role"] for m in said["messages"]] == ["user", "assistant"] and said["messages"][-1]["kind"] == "plan"
        built = await c.post(f"/api/chats/{chat['id']}/build", json={"plan_approval": False, "final_review": False})
        assert built.status_code == 201 and built.json()["project"] == project  # builds on the same files
        await wait_done(c, built.json()["run_id"])
        assert (await c.post("/api/chats", json={"project": "bad name!"})).status_code == 400
