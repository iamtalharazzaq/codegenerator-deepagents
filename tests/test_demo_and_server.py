import asyncio
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from orchestrator.demo import DemoModel
from orchestrator.server import Settings, create_app


def make_app(tmp_path: Path, scenario: str = "recover", concurrency: int = 1):
    settings = Settings(workspaces_root=tmp_path, concurrency=concurrency, demo=True)
    return create_app(settings, model_factory=lambda: DemoModel(delay=0, scenario=scenario), sandbox_factory=lambda: None)


async def wait_done(client: httpx.AsyncClient, run_id: str, timeout: float = 20) -> dict:
    for _ in range(int(timeout / 0.05)):
        info = (await client.get(f"/api/runs/{run_id}")).json()
        if not info["active"] and info["meta"].get("status") != "running":
            return info
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def events_of(client: httpx.AsyncClient, run_id: str, headers: dict | None = None) -> list[dict]:
    out = []
    async with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers or {}) as r:
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: ") and name == "run_event":
                out.append(json.loads(line[6:]))
    return out


async def test_demo_run_recovers_after_one_qa_failure_and_delivers_a_zip(tmp_path):
    async with client_for(make_app(tmp_path, concurrency=2)) as c:
        r = await c.post("/api/runs", json={"request": "Add password reset", "plan_approval": False})
        assert r.status_code == 201
        run_id = r.json()["run_id"]
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "passed"
        live = [t for t in info["tasks"] if t["status"] != "superseded"]
        assert {t["role"] for t in live} >= {"code_analyst", "solution_architect", "qa_engineer", "backend_developer"}
        assert all(t["status"] == "pass" for t in live)
        qa = next(t for t in live if t["role"] == "qa_engineer")
        assert qa["attempt"] == 2  # failed once, passed on the retry
        assert info["has_zip"] and "# Run" in info["report"]
        z = await c.get(f"/api/runs/{run_id}/delivery.zip")
        assert z.status_code == 200
        (tmp_path / "out.zip").write_bytes(z.content)
        names = zipfile.ZipFile(tmp_path / "out.zip").namelist()
        assert "backend/app.py" in names and "docs/orchestrator/report.md" in names
        evs = await events_of(c, run_id)
        kinds = [e["type"] for e in evs]
        assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
        assert "tool_call" in kinds and "replan_started" in kinds
        # db, backend and frontend were started together (concurrency 2), not one after the other
        started = [e["task"]["role"] for e in evs if e["type"] == "task_started"]
        assert set(started[2:4]) <= {"database_engineer", "backend_developer", "frontend_developer"}


async def test_events_replay_from_last_event_id(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "plan_approval": False})).json()["run_id"]
        await wait_done(c, run_id)
        everything = await events_of(c, run_id)
        tail = await events_of(c, run_id, {"Last-Event-ID": str(everything[3]["seq"])})
        assert [e["seq"] for e in tail] == [e["seq"] for e in everything[4:]]


async def test_plan_approval_blocks_until_approved(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "x"})).json()["run_id"]
        for _ in range(100):
            await asyncio.sleep(0.05)
            r = await c.post(f"/api/runs/{run_id}/approve", json={"approved": True})
            if r.status_code == 200:
                break
        assert r.status_code == 200
        assert (await c.post(f"/api/runs/{run_id}/approve", json={"approved": True})).status_code == 409
        assert (await wait_done(c, run_id))["meta"]["status"] == "passed"


async def test_rejecting_the_plan_stops_the_run_with_nothing_started(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "x"})).json()["run_id"]
        for _ in range(100):
            await asyncio.sleep(0.05)
            if (await c.post(f"/api/runs/{run_id}/approve", json={"approved": False})).status_code == 200:
                break
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "stopped"
        assert all(t["attempt"] == 0 for t in info["tasks"])


async def test_escalation_offers_resume_and_a_labelled_partial_zip(tmp_path):
    async with client_for(make_app(tmp_path, scenario="escalate")) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "plan_approval": False})).json()["run_id"]
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "escalated" and not info["has_zip"]
        assert (await c.get(f"/api/runs/{run_id}/delivery.zip")).status_code == 409  # not offered by default
        part = await c.get(f"/api/runs/{run_id}/delivery.zip?partial=1")
        assert part.status_code == 200
        (tmp_path / "p.zip").write_bytes(part.content)
        assert "PARTIAL.txt" in zipfile.ZipFile(tmp_path / "p.zip").namelist()
        # resume with guidance: the escalated QA task gets a fresh budget and the planner sees the guidance
        res = await c.post(f"/api/runs/{run_id}/resume", json={"guidance": "skip the flaky test"})
        assert res.status_code == 200 and res.json()["start_at"] == "plan"
        again = await wait_done(c, run_id)
        assert again["meta"]["status"] == "escalated"  # the demo QA still fails in this scenario
        evs = await events_of(c, run_id)
        assert "run_resumed" in [e["type"] for e in evs]
        seqs = [e["seq"] for e in evs]
        assert seqs == sorted(set(seqs))  # sequence numbers continue across the resume


async def test_one_run_at_a_time_per_project_and_input_validation(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        assert (await c.post("/api/runs", json={"request": "x", "project": "../evil"})).status_code == 400
        assert (await c.post("/api/runs", json={"request": ""})).status_code == 422
        await c.post("/api/runs", json={"request": "a"})  # waits for approval, so it stays active
        assert (await c.post("/api/runs", json={"request": "b"})).status_code == 409
        assert (await c.get("/api/runs/zzzzzzzz")).status_code == 404
        assert (await c.get("/api/runs/00000000/artifacts/../../x")).status_code in (404, 422)


async def test_list_and_artifacts_and_cancel(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "list me"})).json()["run_id"]
        rows = (await c.get("/api/runs")).json()
        assert rows[0]["run_id"] == run_id and rows[0]["request"] == "list me"
        assert (await c.post(f"/api/runs/{run_id}/cancel")).status_code == 200
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "stopped"
        assert (await c.get(f"/api/runs/{run_id}/artifacts/report.md")).status_code in (200, 404)
        assert (await c.get(f"/api/runs/{run_id}/artifacts/passwd")).status_code == 404


async def test_a_run_left_running_by_a_crash_is_marked_interrupted_on_startup(tmp_path):
    from agent.tools.workspace import Workspace

    from orchestrator.runner import read_meta, write_meta

    ws = Workspace(tmp_path, "demo")
    ws.create()
    write_meta(ws, "abcdef01", status="running", request="x")
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        pass
    assert read_meta(ws, "abcdef01")["status"] == "interrupted"


@pytest.mark.parametrize("scenario,status", [("recover", "passed"), ("escalate", "escalated")])
async def test_demo_model_drives_the_graph_without_a_server(tmp_path, scenario, status):
    from agent.tools.workspace import Workspace

    from orchestrator.config import RunConfig
    from orchestrator.events import EventLog
    from orchestrator.runner import run_graph
    from orchestrator.task import TaskLog

    ws = Workspace(tmp_path, "d")
    ws.create()
    state = {"request": "r", "workspace": ws, "run_id": "r1", "model": DemoModel(delay=0, scenario=scenario),
             "task_log": TaskLog("r1", "r", []), "last_failure": None, "events": EventLog(), "config": RunConfig(concurrency=3)}
    result = await run_graph(state)
    assert result["status"] == status
