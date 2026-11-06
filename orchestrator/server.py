"""Web service: start runs, stream their events, approve plans, resume, download the zip.

Everything a run does is already in `runs/<run_id>/` (events.jsonl, task_log.json, meta.json, artifacts, report.md,
delivery.zip), so the service is a thin layer: it starts the graph in the background, relays the event log over
Server-Sent Events (with `Last-Event-ID` replay), and serves files. One active run per project.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.tools.sandbox import SandboxClient
from agent.tools.workspace import Workspace
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from orchestrator import chat as chats
from orchestrator.config import RunConfig
from orchestrator.delivery import build_zip, is_deliverable
from orchestrator.events import EventLog
from orchestrator.runner import (
    new_project_name,
    prepare_workspace,
    read_meta,
    resume_fields,
    run_graph,
    run_path,
    write_meta,
    zip_filename,
)
from orchestrator.secrets import scan_secrets
from orchestrator.task import TaskLog, load_task_log
from orchestrator.team import OrchestratorState

RUN_ID_RE = re.compile(r"^[0-9a-f]{8}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PREVIEW_BYTES = 200_000  # the largest file the Files tab will show
ARTIFACT_RE = re.compile(r"^(?:report|[0-9a-f]{8}(?:\.attempt\d+)?)\.md$")
RESUMABLE = ("escalated", "stopped", "error", "interrupted")


@dataclass
class Settings:
    workspaces_root: Path
    default_project: str | None = None  # None: every run gets its own new project
    concurrency: int = 1
    web_dist: Path | None = None
    demo: bool = False
    demo_sandbox: bool = False  # in demo mode, let QA really call the sandbox (ORCH_DEMO_SANDBOX=1)

    @classmethod
    def from_env(cls) -> Settings:
        dist = os.environ.get("WEB_DIST")
        return cls(
            workspaces_root=Path(os.environ.get("WORKSPACES_ROOT", "/app/workspaces")),
            default_project=os.environ.get("DEFAULT_PROJECT") or None,
            concurrency=int(os.environ.get("ORCH_CONCURRENCY", "1")),
            web_dist=Path(dist) if dist else None,
            demo=os.environ.get("ORCH_DEMO") == "1",
            demo_sandbox=os.environ.get("ORCH_DEMO_SANDBOX") == "1",
        )


class StartRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    project: str | None = None
    plan_approval: bool = True
    final_review: bool = True  # pause before the zip is built and ask whether anything should change
    concurrency: int | None = Field(default=None, ge=1, le=8)


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    plan: bool = False  # answer with the plan in key points (the first message of a conversation asks for it)


class CreateChatRequest(BaseModel):
    project: str | None = None  # an existing project to continue (its files are built on)


class BuildRequest(BaseModel):
    plan_approval: bool = True
    final_review: bool = True
    concurrency: int | None = Field(default=None, ge=1, le=8)


class ApproveRequest(BaseModel):
    approved: bool
    # Not approved + feedback: the plan goes back to the Project Manager to revise. Not approved, no feedback: stop.
    feedback: str | None = Field(default=None, max_length=4000)


class ReviewRequest(BaseModel):
    accept: bool
    changes: str | None = Field(default=None, max_length=4000)


class ResumeRequest(BaseModel):
    guidance: str | None = Field(default=None, max_length=4000)


@dataclass
class RunHandle:
    run_id: str
    workspace: Workspace
    events: EventLog
    task: asyncio.Task[Any] | None = None
    approval: asyncio.Future[dict[str, Any]] | None = None
    review: asyncio.Future[dict[str, Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()


def create_app(
    settings: Settings | None = None,
    model_factory: Callable[[], BaseChatModel] | None = None,
    sandbox_factory: Callable[[], SandboxClient | None] | None = None,
) -> FastAPI:
    cfg = settings or Settings.from_env()
    if model_factory is None:
        if cfg.demo:
            from orchestrator.demo import DemoModel

            model_factory = DemoModel
        else:
            from orchestrator.cli import build_model

            model_factory = build_model
    if sandbox_factory is None:
        sandbox_factory = SandboxClient if (cfg.demo_sandbox or not cfg.demo) else (lambda: None)
    handles: dict[str, RunHandle] = {}
    app = FastAPI(title="Orchestrator", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------ helpers

    def workspace_for(project: str) -> Workspace:
        if not PROJECT_RE.match(project):
            raise HTTPException(400, "Project names use letters, numbers, - and _ (up to 40).")
        return Workspace(cfg.workspaces_root, project)

    def find(run_id: str) -> Workspace:
        if not RUN_ID_RE.match(run_id):
            raise HTTPException(404, "No such run.")
        if run_id in handles:
            return handles[run_id].workspace
        for meta in sorted(cfg.workspaces_root.glob(f"*/runs/{run_id}/meta.json")):
            return Workspace(cfg.workspaces_root, meta.parent.parent.parent.name)
        raise HTTPException(404, "No such run.")

    def project_busy(project: str) -> bool:
        return any(h.active and h.workspace.path.name == project for h in handles.values())

    def run_config(concurrency: int | None, plan_approval: bool, final_review: bool) -> RunConfig:
        return RunConfig(
            concurrency=concurrency or cfg.concurrency, plan_approval=plan_approval, final_review=final_review, require_plan=True, max_fix_rounds=2,
            retry_backoff_s=2.0, model_retry_wait_s=3.0,
        )

    async def execute(handle: RunHandle, state: OrchestratorState) -> None:
        sandbox = state.get("sandbox_client")
        try:
            await run_graph(state)
        finally:
            handle.approval = None
            handle.review = None
            if sandbox is not None:
                await sandbox.close()

    def launch(handle: RunHandle, state: OrchestratorState) -> None:
        async def approve(payload: dict[str, Any]) -> dict[str, Any]:
            handle.approval = asyncio.get_running_loop().create_future()
            return await handle.approval

        async def review(payload: dict[str, Any]) -> dict[str, Any]:
            handle.review = asyncio.get_running_loop().create_future()
            return await handle.review

        state["approve"] = approve if state["config"].plan_approval else None  # type: ignore[typeddict-item]
        state["review"] = review if state["config"].final_review else None  # type: ignore[typeddict-item]
        handle.task = asyncio.create_task(execute(handle, state))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # A run still marked "running" when the service starts was cut off; it can be resumed.
        for meta_file in cfg.workspaces_root.glob("*/runs/*/meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("status") == "running":
                project = meta_file.parent.parent.parent.name
                write_meta(Workspace(cfg.workspaces_root, project), meta_file.parent.name, status="interrupted")
        yield

    app.router.lifespan_context = lifespan

    # ------------------------------------------------------------ API

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "demo": cfg.demo}

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return {"default_project": cfg.default_project, "concurrency": cfg.concurrency, "demo": cfg.demo}

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, Any]]:
        """Projects that have runs (the volume may hold other tools' folders too). Newest first."""
        found: dict[str, dict[str, Any]] = {}
        for meta_file in cfg.workspaces_root.glob("*/runs/*/meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = meta_file.parent.parent.parent.name
            row = found.setdefault(name, {"name": name, "runs": 0, "last_run_at": 0.0})
            row["runs"] += 1
            row["last_run_at"] = max(row["last_run_at"], float(meta.get("created_at", 0)))
        return sorted(found.values(), key=lambda r: r["last_run_at"], reverse=True)

    @app.post("/api/runs", status_code=201)
    async def start_run(body: StartRequest) -> dict[str, Any]:
        run_id = uuid4().hex[:8]
        project = body.project or cfg.default_project or new_project_name(body.request, run_id)
        ws = workspace_for(project)
        if project_busy(project):
            raise HTTPException(409, f"Project {project!r} already has a run in progress.")
        base = await asyncio.to_thread(prepare_workspace, ws, run_id)
        events = EventLog(run_path(ws, run_id) / "events.jsonl")
        handle = RunHandle(run_id, ws, events)
        handles[run_id] = handle
        config_ = run_config(body.concurrency, body.plan_approval, body.final_review)
        write_meta(ws, run_id, project=project, request=body.request, status="running", base_commit=base,
                   plan_approval=config_.plan_approval, final_review=config_.final_review, concurrency=config_.concurrency)
        events.emit("run_started", run_id=run_id, project=project, request=body.request,
                    plan_approval=config_.plan_approval, final_review=config_.final_review, concurrency=config_.concurrency)
        state: OrchestratorState = {
            "request": body.request, "workspace": ws, "run_id": run_id, "model": model_factory(),
            "sandbox_client": sandbox_factory(), "task_log": TaskLog(run_id=run_id, request=body.request, tasks=[]),
            "config": config_, "events": events, "base_commit": base,
        }
        launch(handle, state)
        return {"run_id": run_id, "project": project}

    # ------------------------------------------------------------ talk first (a conversation before any run)

    chat_locks: dict[str, asyncio.Lock] = {}

    def chat_or_404(chat_id: str) -> dict[str, Any]:
        found = chats.load_chat(cfg.workspaces_root, chat_id) if re.fullmatch(r"[0-9a-f]{8}", chat_id) else None
        if found is None:
            raise HTTPException(404, "No such conversation.")
        return found

    async def talk(chat_id: str, text: str | None, plan: bool) -> dict[str, Any]:
        async with chat_locks.setdefault(chat_id, asyncio.Lock()):
            chat = chat_or_404(chat_id)
            if text is not None:
                chats.add(chat, "user", text.strip())
            elif not chat["messages"]:
                raise HTTPException(409, "Say what you want to build first.")
            try:
                reply = await chats.ask_model(model_factory(), chat, plan=plan, demo=cfg.demo)
            except Exception as exc:
                chats.save_chat(cfg.workspaces_root, chat)
                raise HTTPException(503, f"The model did not answer ({type(exc).__name__}). Your message is saved: send again in a moment.") from exc
            chats.add(chat, "assistant", reply, "plan" if plan else "")
            chats.save_chat(cfg.workspaces_root, chat)
            return chat

    @app.get("/api/chats")
    async def list_chats() -> list[dict[str, Any]]:
        return chats.list_chats(cfg.workspaces_root)

    @app.post("/api/chats", status_code=201)
    async def create_chat(body: CreateChatRequest | None = None) -> dict[str, Any]:
        project = body.project if body else None
        if project:
            workspace_for(project)  # a bad name is refused here
        return chats.new_chat(cfg.workspaces_root, project)

    @app.get("/api/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        return chat_or_404(chat_id)

    @app.post("/api/chats/{chat_id}/messages")
    async def say(chat_id: str, body: SayRequest) -> dict[str, Any]:
        return await talk(chat_id, body.text, plan=body.plan)

    @app.post("/api/chats/{chat_id}/plan")
    async def draft_plan(chat_id: str) -> dict[str, Any]:
        return await talk(chat_id, None, plan=True)

    @app.post("/api/chats/{chat_id}/build", status_code=201)
    async def build_from_chat(chat_id: str, body: BuildRequest) -> dict[str, Any]:
        chat = chat_or_404(chat_id)
        if not any(m.get("kind") == "plan" for m in chat["messages"]):
            raise HTTPException(409, "Ask for the plan first, so you see what will be built.")
        started = await start_run(StartRequest(
            request=chats.brief_for_run(chat), project=chat.get("project"), plan_approval=body.plan_approval,
            final_review=body.final_review, concurrency=body.concurrency,
        ))
        chat = chat_or_404(chat_id)
        chat["project"] = started["project"]
        chat["run_ids"] = [*chat.get("run_ids", []), started["run_id"]]
        chats.save_chat(cfg.workspaces_root, chat)
        return started

    def waiting_for(run_id: str) -> str | None:
        """What a live run is waiting for the person to decide: its plan, or its finished work. None: it is not waiting."""
        handle = handles.get(run_id)
        if handle is None or not handle.active:
            return None
        if handle.approval is not None and not handle.approval.done():
            return "plan"
        if handle.review is not None and not handle.review.done():
            return "review"
        return None

    @app.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for meta_file in cfg.workspaces_root.glob("*/runs/*/meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tasks: list[dict[str, Any]] = []
            log_file = meta_file.parent / "task_log.json"
            if log_file.exists():
                try:
                    tasks = json.loads(log_file.read_text(encoding="utf-8")).get("tasks", [])
                except (OSError, json.JSONDecodeError):
                    tasks = []
            live = [t for t in tasks if t["status"] != "superseded"]
            rows.append({
                "run_id": meta["run_id"], "project": meta.get("project"), "request": meta.get("request", ""),
                # A run that is waiting for a decision is not "running": it is not doing anything until the person answers.
                "status": "needs_approval" if waiting_for(meta["run_id"]) else meta.get("status", "unknown"),
                "waiting_for": waiting_for(meta["run_id"]), "reason": meta.get("reason"), "created_at": meta.get("created_at", 0),
                "tasks_done": sum(t["status"] == "pass" for t in live), "tasks_total": len(live),
            })
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        ws = find(run_id)
        meta = read_meta(ws, run_id) or {}
        rdir = run_path(ws, run_id)
        tasks: list[dict[str, Any]] = []
        if (rdir / "task_log.json").exists():
            tasks = [asdict(t) for t in load_task_log(rdir / "task_log.json").tasks]
        report = (rdir / "report.md").read_text(encoding="utf-8") if (rdir / "report.md").exists() else None
        return {"meta": meta, "tasks": tasks, "report": report, "waiting_for": waiting_for(run_id),
                "has_zip": (rdir / "delivery.zip").exists(), "active": run_id in handles and handles[run_id].active}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request, after: int = 0) -> StreamingResponse:
        ws = find(run_id)
        handle = handles.get(run_id)
        last = request.headers.get("last-event-id")
        start = int(last) if last and last.isdigit() else after
        log = handle.events if handle else EventLog(run_path(ws, run_id) / "events.jsonl")
        live = handle is not None and handle.active

        def frame(event: dict[str, Any]) -> str:
            return f"id: {event['seq']}\nevent: run_event\ndata: {json.dumps(event)}\n\n"

        async def stream() -> AsyncIterator[str]:
            queue = log.subscribe() if live else None
            sent = start
            try:
                last_type = None
                for event in log.since(start):  # history in full: a resumed run has several run_finished events
                    sent = event["seq"]
                    last_type = event["type"]
                    yield frame(event)
                if last_type == "run_finished" or queue is None or not (handle and handle.active):
                    yield "event: end\ndata: {}\n\n"
                    return
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), 15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event["seq"] <= sent:
                        continue
                    sent = event["seq"]
                    yield frame(event)
                    if event["type"] == "run_finished":
                        yield "event: end\ndata: {}\n\n"
                        return
            finally:
                if queue is not None:
                    log.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{run_id}/approve")
    async def approve_plan(run_id: str, body: ApproveRequest) -> dict[str, bool]:
        handle = handles.get(run_id)
        if handle is None or handle.approval is None or handle.approval.done():
            raise HTTPException(409, "This run is not waiting for a plan decision.")
        handle.approval.set_result({"approved": body.approved, "feedback": (body.feedback or "").strip()})
        return {"ok": True}

    @app.post("/api/runs/{run_id}/review")
    async def review_result(run_id: str, body: ReviewRequest) -> dict[str, bool]:
        """The person's decision on the finished work: deliver it, or ask for changes."""
        handle = handles.get(run_id)
        if handle is None or handle.review is None or handle.review.done():
            raise HTTPException(409, "This run is not waiting for a review.")
        if not body.accept and not (body.changes or "").strip():
            raise HTTPException(422, "Say what should change.")
        handle.review.set_result({"accept": body.accept, "changes": (body.changes or "").strip()})
        return {"ok": True}

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str, body: ResumeRequest) -> dict[str, Any]:
        ws = find(run_id)
        meta = read_meta(ws, run_id) or {}
        if run_id in handles and handles[run_id].active:
            raise HTTPException(409, "This run is still running.")
        if meta.get("status") not in RESUMABLE:
            raise HTTPException(409, f"A run that is {meta.get('status')!r} cannot be resumed.")
        if project_busy(ws.path.name):
            raise HTTPException(409, f"Project {ws.path.name!r} already has a run in progress.")
        log = load_task_log(run_path(ws, run_id) / "task_log.json")
        carry_on = resume_fields(ws, run_id, log, body.guidance)  # read before the status is rewritten below
        handle = handles.get(run_id) or RunHandle(run_id, ws, EventLog(run_path(ws, run_id) / "events.jsonl"))
        handles[run_id] = handle
        try:
            await asyncio.to_thread(ws.branch, f"run/{run_id}")
        except RuntimeError:
            pass
        # The plan decision is not skipped by a resume: a plan that was never approved is asked about again.
        config_ = run_config(meta.get("concurrency"), bool(meta.get("plan_approval", False)), bool(meta.get("final_review", True)))
        write_meta(ws, run_id, status="running", reason=None)
        handle.events.emit("run_resumed", run_id=run_id, guidance=body.guidance or "")
        state: OrchestratorState = {
            "request": log.request, "workspace": ws, "run_id": run_id, "model": model_factory(),
            "sandbox_client": sandbox_factory(), "task_log": log,
            "config": config_, "events": handle.events, "base_commit": meta.get("base_commit"),
        }
        state.update(carry_on)  # type: ignore[typeddict-item]
        launch(handle, state)
        return {"run_id": run_id}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, bool]:
        handle = handles.get(run_id)
        if handle is None or not handle.active or handle.task is None:
            raise HTTPException(409, "This run is not running.")
        handle.task.cancel()
        await asyncio.gather(handle.task, return_exceptions=True)
        # A task cancelled before it started never reaches run_graph's own cleanup, so finish the record here.
        ws = handle.workspace
        if (read_meta(ws, run_id) or {}).get("status") == "running":
            write_meta(ws, run_id, status="stopped", reason="cancelled")
        if handle.events.last_type != "run_finished":
            handle.events.emit("run_finished", status="stopped", reason="cancelled", message="The run was cancelled.")
        return {"ok": True}

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    async def artifact(run_id: str, name: str) -> PlainTextResponse:
        ws = find(run_id)
        if not ARTIFACT_RE.match(name):
            raise HTTPException(404, "No such artifact.")
        path = run_path(ws, run_id) / name
        if not path.exists():
            raise HTTPException(404, "No such artifact.")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/runs/{run_id}/files/{path:path}")
    async def preview_file(run_id: str, path: str) -> PlainTextResponse:
        """One file of the project, as text, for the Files tab. Same exclusions as the zip (.git, real .env, caches),
        nothing outside the project folder, no symlinks, and no binary or very large files."""
        root = find(run_id).work.resolve()
        candidate = root / path.lstrip("/")
        target = candidate.resolve()
        if not target.is_relative_to(root) or candidate.is_symlink() or not target.is_file() or not is_deliverable(target.relative_to(root)):
            raise HTTPException(404, "No such file.")
        data = await asyncio.to_thread(target.read_bytes)
        if len(data) > PREVIEW_BYTES or b"\0" in data:
            raise HTTPException(415, "This file is too large or not text, so it cannot be previewed.")
        return PlainTextResponse(data.decode("utf-8", errors="replace"))

    @app.get("/api/runs/{run_id}/delivery.zip")
    async def delivery(run_id: str, partial: bool = False) -> FileResponse:
        ws = find(run_id)
        meta = read_meta(ws, run_id) or {}
        rdir = run_path(ws, run_id)
        if meta.get("status") == "passed":
            zip_path = rdir / "delivery.zip"
            if not zip_path.exists():
                raise HTTPException(409, "No zip was built: the secret scan blocked it. See the report.")
            return FileResponse(zip_path, media_type="application/zip", filename=zip_filename(ws.path.name, run_id))
        if not partial:
            raise HTTPException(409, "This run did not finish. Ask for a partial zip to download what exists.")
        if run_id in handles and handles[run_id].active:
            raise HTTPException(409, "This run is still running.")
        findings = scan_secrets(ws.work)
        if findings:
            raise HTTPException(409, f"Not built: the secret scan found {len(findings)} possible secret(s), e.g. {findings[0].path}.")
        dest = rdir / "delivery-partial.zip"
        await asyncio.to_thread(build_zip, ws.work, rdir, dest, partial=True)
        return FileResponse(dest, media_type="application/zip", filename=zip_filename(ws.path.name, run_id, partial=True))

    # ------------------------------------------------------------ the built frontend

    dist = cfg.web_dist
    if dist is not None and dist.exists():
        index = dist / "index.html"
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve() if path else index
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app
