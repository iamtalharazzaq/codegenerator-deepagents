"""Talk first: a conversation with the Project Manager before any work starts.

The person describes a problem; the Project Manager (the model, with no tools) asks, suggests and, when asked, drafts a
plan. Nothing is built in this chat. "Build" turns the conversation, and the plan the person agreed to, into the request
of a normal run (which still shows its plan for approval and asks for a final review). A chat belongs to a project once a
run was started from it, so the next build from the same chat continues that project.

Chats are JSON files under `<workspaces root>/_chats/`, outside every project, so they survive restarts and can be resumed.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from orchestrator.roles import ROLES_DIR, describe_team

CHATS_DIR = "_chats"
HISTORY_CHARS = 5000  # what is sent back to the model of the conversation so far (the window is small)
BRIEF_CHARS = 3500
MODEL_TRIES = 3
RETRY_WAIT_S = 2.0  # first pause between tries (doubles each time)


def chats_dir(root: Path) -> Path:
    return root / CHATS_DIR


def chat_path(root: Path, chat_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8}", chat_id):
        raise ValueError("bad chat id")
    return chats_dir(root) / f"{chat_id}.json"


def new_chat(root: Path, project: str | None = None) -> dict[str, Any]:
    now = time.time()
    chat: dict[str, Any] = {"id": uuid.uuid4().hex[:8], "title": "", "messages": [], "project": project, "run_ids": [], "created_at": now, "updated_at": now}
    save_chat(root, chat)
    return chat


def load_chat(root: Path, chat_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(chat_path(root, chat_id).read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None


def save_chat(root: Path, chat: dict[str, Any]) -> None:
    chat["updated_at"] = time.time()
    path = chat_path(root, chat["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(chat, indent=1), encoding="utf-8")
    tmp.replace(path)


def list_chats(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in chats_dir(root).glob("*.json"):
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({"id": c["id"], "title": c.get("title") or "New conversation", "updated_at": c.get("updated_at", 0), "messages": len(c.get("messages", [])),
                     "project": c.get("project"), "runs": len(c.get("run_ids", []))})
    return sorted(rows, key=lambda r: r["updated_at"], reverse=True)


def system_prompt() -> str:
    text = (ROLES_DIR / "project_manager" / "discuss.md").read_text(encoding="utf-8").strip()
    return text.replace("{team}", describe_team())


def plan_request() -> str:
    return (ROLES_DIR / "project_manager" / "plan_request.md").read_text(encoding="utf-8").strip()


def history(chat: dict[str, Any]) -> list[BaseMessage]:
    """The newest messages that fit `HISTORY_CHARS`, plus the very first one (it states the problem)."""
    msgs = chat["messages"]
    kept: list[dict[str, Any]] = []
    used = 0
    for m in reversed(msgs):
        used += len(m["text"])
        if used > HISTORY_CHARS and kept:
            break
        kept.append(m)
    kept.reverse()
    if msgs and kept[0] is not msgs[0] and msgs[0]["role"] == "user":
        kept.insert(0, msgs[0])
    return [HumanMessage(content=m["text"]) if m["role"] == "user" else AIMessage(content=m["text"]) for m in kept]


def clean(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


DEMO_QUESTION = "Happy to help. Two quick questions: who will use it, and should it be a command-line tool or a web page? I'd suggest the smallest version first: a command-line tool."
DEMO_PLAN = ("- **Backend Developer**: create app.py with the main function (app.py)\n- **QA Engineer**: create test_app.py and run it (test_app.py)\n\n"
             "Run it with: `python app.py`\n\nBuild this, or change something?")


async def ask_model(model: BaseChatModel, chat: dict[str, Any], *, plan: bool, demo: bool = False, wait_s: float | None = None) -> str:
    """The Project Manager's next message. A slow or briefly absent model server is tried again before giving up."""
    if demo:
        return DEMO_PLAN if plan else DEMO_QUESTION
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt()), *history(chat)]
    if plan:
        messages.append(HumanMessage(content=plan_request()))
    from agent.llm.client import LLMUnavailable
    from agent.llm.langchain_model import UNAVAILABLE_ERRORS

    # LangChain's own retry for a plain model call (this is a chat, not an agent, so no middleware applies)
    retrying = model.with_retry(
        retry_if_exception_type=(*UNAVAILABLE_ERRORS, LLMUnavailable), stop_after_attempt=MODEL_TRIES,
        wait_exponential_jitter=True, exponential_jitter_params={"initial": RETRY_WAIT_S if wait_s is None else wait_s, "max": 30.0, "jitter": 0.0},
    )
    reply = await retrying.ainvoke(messages)
    text = clean(reply.content if isinstance(reply.content, str) else str(reply.content))
    return text or "I did not get an answer from the model. Please send that again."


def add(chat: dict[str, Any], role: str, text: str, kind: str = "") -> None:
    chat["messages"].append({"role": role, "text": text, "kind": kind, "ts": time.time()})
    if role == "user" and not chat.get("title"):
        chat["title"] = " ".join(text.split())[:80]


def brief_for_run(chat: dict[str, Any]) -> str:
    """The request a run starts from: what the person said, and the plan they were shown last."""
    said = [m["text"].strip()[:400] for m in chat["messages"] if m["role"] == "user"][-4:]  # 4 x 400 + the plan (1,500) fit BRIEF_CHARS
    plans = [m["text"] for m in chat["messages"] if m["role"] == "assistant" and m.get("kind") == "plan"]
    first = " ".join(said[0].split())[:200] if said else ""
    parts = [first, "As agreed in conversation with the person:\n" + "\n".join(f"- {s}" for s in said)]
    if plans:
        parts.append("The plan they were shown (follow it unless it is wrong):\n" + plans[-1].strip()[:1500])
    if chat.get("project"):
        parts.append("This continues earlier work in the same project: build on the files that exist.")
    return "\n\n".join(parts)
