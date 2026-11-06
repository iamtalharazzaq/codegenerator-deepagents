"""Does the real Project Manager pick the smallest team? Runs the whole team (real model, live sandbox) on simple
requests and prints which specialists it delegated to. Same container setup as eval_examples.py."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path

from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace, git

from orchestrator.cli import build_model
from orchestrator.config import RunConfig
from orchestrator.events import EventLog
from orchestrator.task import TaskLog
from orchestrator.team import run_team

REQUESTS = [
    "Make a calculator",
    "Write a Python function that reverses a string, with a test",
    "Create a small command-line todo list in Python",
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--out", default="/app/workspaces/eval_team_size.json")
    ap.add_argument("--root", default="/app/workspaces")
    args = ap.parse_args()
    model = build_model()
    rows = []
    for rep in range(args.reps):
        for request in REQUESTS:
            ws = Workspace(Path(args.root), f"abtest-{uuid.uuid4().hex[:8]}")
            ws.create()
            ws.init_git()
            events = EventLog(ws.path / "runs" / "r1" / "events.jsonl")
            state = {
                "request": request, "workspace": ws, "run_id": "r1", "model": model, "task_log": TaskLog("r1", request, []),
                "events": events, "sandbox_client": SandboxClient(), "base_commit": git(ws.work, "rev-parse", "HEAD"),
                "config": RunConfig(require_plan=True, max_fix_rounds=2, task_timeout_s=420, run_timeout_s=900),
            }
            started = time.monotonic()
            result = await run_team(state)  # type: ignore[arg-type]
            tasks = result["task_log"].tasks
            files = sorted(str(p.relative_to(ws.work)) for p in ws.work.rglob("*") if p.is_file() and ".git" not in p.parts)
            row = {
                "request": request, "rep": rep, "status": result["status"], "reason": result["end_reason"], "seconds": round(time.monotonic() - started),
                "specialists": sorted({t.role for t in tasks}), "tasks": len(tasks), "files": files,
                "examples": sorted({e for t in tasks for e in t.examples}),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
            Path(args.out).write_text(json.dumps(rows, indent=1))
            shutil.rmtree(ws.path, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
