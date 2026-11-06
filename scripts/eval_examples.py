# ruff: noqa: C408
"""Examples ON versus OFF on identical tasks, against the real model and the live sandbox.

For each task a scripted Project Manager delegates the SAME instruction to one real specialist (the model is the real
one, so the specialist's words, tool calls and files are real). The only difference between the two conditions is
`RunConfig.examples`. Every task has an automatic check of the result, independent of what the specialist claimed.

Run inside the orchestrator image on the codewright network (it needs the model URL and the sandbox):

    docker run --rm --network codewright_default -v codewright_workspaces:/app/workspaces \
        -v $PWD/scripts:/scripts:ro -e LLM_REMOTE_GPU_URL=... codegenerator-deepagents:dev \
        python /scripts/eval_examples.py --reps 3 --out /app/workspaces/eval_examples.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace, git
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from orchestrator.cli import build_model
from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.task import TaskLog
from orchestrator.team import run_team

OK_FOOTER = "Done.\n---\nstatus: pass\nreason: ok\n---"


def sh(work: Path, code: str) -> str:
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.')\n" + code], cwd=work, capture_output=True, text=True, timeout=30, check=False)
    return (r.stdout + r.stderr).strip()


def read(work: Path, rel: str) -> str:
    p = work / rel
    return p.read_text(errors="replace").replace("-", " ") if p.is_file() else ""  # "out-of-scope" reads as "out of scope"


def lines(text: str) -> int:
    return len([ln for ln in text.splitlines() if ln.strip()])


# ---- the tasks: (role, instruction as the Project Manager would write it, files to start from, check(work) -> bool)
def check_backend(w: Path) -> bool:
    out = sh(w, "import calculator as c\nassert c.add(2,3)==5 and c.subtract(5,3)==2 and c.multiply(4,3)==12 and c.divide(8,2)==4\n"
                "try:\n c.divide(1,0)\nexcept ValueError:\n print('OK')")
    extras = [p.name for p in w.iterdir() if p.is_file() and p.name not in ("calculator.py",) and not p.name.startswith(".")]
    return out.endswith("OK") and not extras


CALC = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n\ndef multiply(a, b):\n    return a * b\n\ndef divide(a, b):\n    if b == 0:\n        raise ValueError('division by zero')\n    return a / b\n"
APP_BAD = "import os\nSECRET_KEY = 'hunter2-prod-key'\n\ndef calc():\n    expr = input('expression: ')\n    return eval(expr)\n\nif __name__ == '__main__':\n    print(calc())\n"
TEMP_BUG = "def c_to_f(c):\n    return c * 9 / 5 - 32\n"

TASKS: list[dict[str, Any]] = [
    dict(id="backend-calculator", role="backend-developer",
         brief="Create calculator.py with functions add, subtract, multiply and divide (each takes a and b; divide raises ValueError when b is 0).\nWRITES: calculator.py\nDONE: calculator.py defines add, subtract, multiply, divide",
         files={}, check=check_backend),
    dict(id="qa-calculator", role="qa-engineer",
         brief="Write tests for calculator.py (add, subtract, multiply, divide, divide by zero) and run them.\nWRITES: test_calculator.py\nDONE: the tests pass",
         files={"calculator.py": CALC},
         check=lambda w: len(re.findall(r"def test_", read(w, "test_calculator.py"))) >= 4),
    dict(id="security-review", role="security-engineer",
         brief="Review the project for security problems.\nWRITES: docs/security.md\nDONE: the review file lists each finding with its file and line",
         files={"app.py": APP_BAD}, expect_fail=True,
         check=lambda w: bool(re.search(r"app\.py:\d+", read(w, "docs/security.md"))) and "eval" in read(w, "docs/security.md").lower()
         and "files reviewed" in read(w, "docs/security.md").lower()),
    dict(id="analyst-notes", role="business-analyst",
         brief="Write notes for the request 'a command-line todo list'.\nWRITES: docs/notes.md\nDONE: docs/notes.md exists",
         files={},
         check=lambda w: all(h in read(w, "docs/notes.md").lower() for h in ("goal", "users", "constraints", "open questions"))
         and "user stor" not in read(w, "docs/notes.md").lower() and lines(read(w, "docs/notes.md")) <= 30),
    dict(id="product-requirements", role="product-manager",
         brief="Write requirements for 'a command-line todo list'. Notes: docs/notes.md.\nWRITES: docs/requirements.md\nDONE: docs/requirements.md exists",
         files={"docs/notes.md": "# Notes\nGoal: a command-line todo list.\nUsers: Unknown.\nOpen questions: Where are items stored?\n"},
         check=lambda w: "out of scope" in read(w, "docs/requirements.md").lower()
         and len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s", read(w, "docs/requirements.md"))) <= 12 and lines(read(w, "docs/requirements.md")) <= 50
         and not re.search(r"\b(react|postgres|docker|kubernetes|mongodb)\b", read(w, "docs/requirements.md").lower())),
    dict(id="writer-readme", role="technical-writer",
         brief="Write README.md for this project.\nWRITES: README.md\nDONE: README.md explains how to run and test it",
         files={"app.py": "print('hello')\n", "requirements.txt": "pytest\n", "test_app.py": "def test_ok():\n    assert True\n"},
         check=lambda w: "python app.py" in read(w, "README.md") and not re.search(r"tbd|coming soon|todo", read(w, "README.md").lower())
         and lines(read(w, "README.md")) <= 50),
    dict(id="frontend-counter", role="frontend-developer",
         brief="Create index.html with a number display starting at 0 and a button 'Add one' that increases it.\nWRITES: index.html\nDONE: index.html exists",
         files={},
         check=lambda w: "<button" in read(w, "index.html").lower() and not re.search(r"https?://", read(w, "index.html"))
         and [p.name for p in w.iterdir() if p.is_file() and not p.name.startswith(".")] == ["index.html"]),
    dict(id="code-review", role="code-analyst",
         brief="Review temp.py against this requirement: c_to_f(c) returns the Fahrenheit value (c * 9 / 5 + 32).\nWRITES: docs/review.md\nDONE: the review says whether the requirement is met",
         files={"temp.py": TEMP_BUG}, expect_fail=True,
         check=lambda w: "temp.py" in read(w, "docs/review.md") and bool(re.search(r"32", read(w, "docs/review.md")))),
    dict(id="architect-design", role="solution-architect",
         brief="Design a command-line todo list. Requirements: docs/requirements.md.\nWRITES: docs/architecture.md\nDONE: docs/architecture.md exists",
         files={"docs/requirements.md": "# Requirements\nGoal: a command-line todo list.\n1. Add an item.\n2. List items.\n3. Mark an item done.\nOut of scope: sync, accounts.\n"},
         check=lambda w: "main parts" in read(w, "docs/architecture.md").lower() and lines(read(w, "docs/architecture.md")) <= 60
         and not re.search(r"microservice|message queue|kafka|kubernetes", read(w, "docs/architecture.md").lower())),
    dict(id="designer-screens", role="ui-ux-designer",
         brief="Design the screen for a to-do web page. Requirements: docs/requirements.md.\nWRITES: docs/design.md\nDONE: docs/design.md exists",
         files={"docs/requirements.md": "# Requirements\nGoal: a to-do web page.\n1. Add an item.\n2. List items.\nOut of scope: accounts.\n"},
         check=lambda w: "empty" in read(w, "docs/design.md").lower() and "error" in read(w, "docs/design.md").lower()
         and lines(read(w, "docs/design.md")) <= 60 and "<div" not in read(w, "docs/design.md")),
    dict(id="database-schema", role="database-engineer",
         brief="Design the schema for tasks that belong to users, as a migration.\nWRITES: db/migrations/001_init.sql\nDONE: the migration has an up and a down",
         files={},
         check=lambda w: bool(re.search(r"foreign key|references", read(w, "db/migrations/001_init.sql").lower())) and "down" in read(w, "db/migrations/001_init.sql").lower()
         and "primary key" in read(w, "db/migrations/001_init.sql").lower() and "drop table" in read(w, "db/migrations/001_init.sql").lower()),
    dict(id="devops-dockerfile", role="devops-engineer",
         brief="Add a Dockerfile for the Python script app.py.\nWRITES: Dockerfile, .dockerignore\nDONE: Dockerfile builds",
         files={"app.py": "print('hello')\n", "requirements.txt": "pytest\n"},
         check=lambda w: bool(re.search(r"(?m)^FROM \S+:[^l\s]\S*", read(w, "Dockerfile"))) and "USER" in read(w, "Dockerfile")),
]


class Usage(AsyncCallbackHandler):
    """Collects the prompt-token count the model server reports for every specialist call."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        g = response.generations[0][0] if response.generations and response.generations[0] else None
        meta = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
        self.calls.append((int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))))


class Router(BaseChatModel):
    """Plays the Project Manager (delegate once, then report) and sends every specialist call to the real model."""

    real: Any
    role: str = ""
    brief: str = ""

    @property
    def _llm_type(self) -> str:
        return "router"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # pragma: no cover
        raise NotImplementedError

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        real = self.real.bind_tools(tools, **kwargs)

        async def route(messages: Any, config: Any = None) -> AIMessage:
            msgs = messages if isinstance(messages, list) else messages.to_messages()
            system = str(next((m.content for m in msgs if isinstance(m, SystemMessage)), ""))
            if "You are the Project Manager" not in system:
                return await real.ainvoke(msgs, config)
            if any(isinstance(m, ToolMessage) for m in msgs):
                return AIMessage(content=OK_FOOTER)
            call = {"name": "task", "args": {"description": self.brief, "subagent_type": self.role}, "id": "k1", "type": "tool_call"}
            return AIMessage(content="", tool_calls=[call])

        return RunnableLambda(route)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # pragma: no cover
        return ChatResult(generations=[ChatGeneration(message=await self.bind_tools([]).ainvoke(messages))])


async def one(root: Path, real: Any, task: dict[str, Any], examples: bool, rep: int) -> dict[str, Any]:
    name = f"abtest-{uuid.uuid4().hex[:8]}"
    ws = Workspace(root, name)
    ws.create()
    ws.init_git()
    for rel, text in task["files"].items():
        (ws.work / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws.work / rel).write_text(text)
    if task["files"]:
        git(ws.work, "add", "-A")
        git(ws.work, "-c", "user.name=eval", "-c", "user.email=eval@example.com", "commit", "-m", "start")
    usage = Usage()
    real.callbacks = [*(real.callbacks or []), usage]
    events = EventLog(ws.path / "runs" / "r1" / "events.jsonl")
    state = {
        "request": task["brief"], "workspace": ws, "run_id": "r1", "model": Router(real=real, role=task["role"], brief=task["brief"]),
        "task_log": TaskLog("r1", task["brief"], []), "events": events, "sandbox_client": SandboxClient(),
        "config": RunConfig(examples=examples, task_timeout_s=420, max_nudges=0, max_fix_rounds=0),
        "base_commit": git(ws.work, "rev-parse", "HEAD"),
    }
    started = time.monotonic()
    try:
        result = await run_team(state)  # type: ignore[arg-type]
        t = result["task_log"].tasks[0] if result["task_log"].tasks else None
    except Exception as exc:  # noqa: BLE001
        t, result = None, {"error": f"{type(exc).__name__}: {exc}"[:200]}
    seconds = time.monotonic() - started
    evs = events.since(0)
    try:
        quality = bool(task["check"](ws.work)) if t is not None else False
    except Exception:  # noqa: BLE001
        quality = False
    claimed_ok = (t.status == "fail") if task.get("expect_fail") and t is not None else (t is not None and t.status == "pass")
    row = {
        "task": task["id"], "examples": examples, "rep": rep, "seconds": round(seconds, 1),
        "accepted": claimed_ok, "valid_reply": t is not None and t.failure_kind != "invalid_output",
        "quality": quality, "status": t.status if t else "none", "reason": (t.reason if t else result.get("error", ""))[:120],
        "tool_calls": sum(1 for e in evs if e["type"] == "tool_call"), "shown": t.examples if t else [],
        "sample": {str(p.relative_to(ws.work)): p.read_text(errors="replace")[:500] for p in sorted(ws.work.rglob("*")) if p.is_file() and ".git" not in p.parts and p.stat().st_size < 20000}, "calls": len(usage.calls), "first_prompt_tokens": usage.calls[0][0] if usage.calls else 0, "max_prompt_tokens": max((i for i, _ in usage.calls), default=0),
        "out_tokens": sum(o for _, o in usage.calls),
    }
    real.callbacks = [c for c in real.callbacks if c is not usage]
    shutil.rmtree(ws.path, ignore_errors=True)
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--out", default="eval_examples.json")
    ap.add_argument("--root", default="/app/workspaces")
    args = ap.parse_args()
    real = build_model()
    tasks = [t for t in TASKS if not args.tasks or t["id"] in args.tasks.split(",")]
    plan = [(t, ex, rep) for t in tasks for rep in range(args.reps) for ex in (False, True)]
    random.Random(7).shuffle(plan)  # interleaved, so drift in the model server hits both conditions alike
    rows: list[dict[str, Any]] = []
    for i, (task, ex, rep) in enumerate(plan, 1):
        row = await one(Path(args.root), real, task, ex, rep)
        rows.append(row)
        print(f"[{i}/{len(plan)}] {row['task']:20} examples={'on ' if ex else 'off'} accepted={row['accepted']!s:5} quality={row['quality']!s:5} "
              f"calls={row['calls']} prompt<={row['max_prompt_tokens']} {row['seconds']}s shown={row['shown']}", flush=True)
        Path(args.out).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
