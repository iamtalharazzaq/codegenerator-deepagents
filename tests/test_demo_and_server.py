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
        r = await c.post("/api/runs", json={"request": "Add password reset", "plan_approval": False, "final_review": False})
        assert r.status_code == 201
        run_id = r.json()["run_id"]
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "passed"
        qa = [t for t in info["tasks"] if t["role"] == "qa_engineer"]
        assert [(t["attempt"], t["status"]) for t in qa] == [(1, "fail"), (2, "pass")]  # failed once, passed on the retry
        assert {t["role"] for t in info["tasks"]} >= {"code_analyst", "solution_architect", "backend_developer", "frontend_developer"}
        assert info["has_zip"] and "# Run" in info["report"]
        z = await c.get(f"/api/runs/{run_id}/delivery.zip")
        assert z.status_code == 200
        (tmp_path / "out.zip").write_bytes(z.content)
        names = zipfile.ZipFile(tmp_path / "out.zip").namelist()
        assert "backend/app.py" in names and "docs/orchestrator/report.md" in names
        evs = await events_of(c, run_id)
        kinds = [e["type"] for e in evs]
        assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
        assert "tool_call" in kinds and kinds.count("todos_updated") == 2  # the to-do list was updated after QA failed
        # database, backend and frontend were started together (concurrency 2), not one after the other
        started = [e["task"]["role"] for e in evs if e["type"] == "task_started"]
        assert set(started[2:4]) <= {"database_engineer", "backend_developer", "frontend_developer"}


async def test_events_replay_from_last_event_id(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "plan_approval": False, "final_review": False})).json()["run_id"]
        await wait_done(c, run_id)
        everything = await events_of(c, run_id)
        tail = await events_of(c, run_id, {"Last-Event-ID": str(everything[3]["seq"])})
        assert [e["seq"] for e in tail] == [e["seq"] for e in everything[4:]]


async def test_plan_approval_blocks_until_approved(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "final_review": False})).json()["run_id"]
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
        run_id = (await c.post("/api/runs", json={"request": "x", "final_review": False})).json()["run_id"]
        for _ in range(100):
            await asyncio.sleep(0.05)
            if (await c.post(f"/api/runs/{run_id}/approve", json={"approved": False})).status_code == 200:
                break
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "stopped" and info["tasks"] == []


async def test_escalation_offers_resume_and_a_labelled_partial_zip(tmp_path):
    async with client_for(make_app(tmp_path, scenario="escalate")) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "plan_approval": False, "final_review": False})).json()["run_id"]
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "escalated" and not info["has_zip"]
        assert (await c.get(f"/api/runs/{run_id}/delivery.zip")).status_code == 409  # not offered by default
        part = await c.get(f"/api/runs/{run_id}/delivery.zip?partial=1")
        assert part.status_code == 200
        (tmp_path / "p.zip").write_bytes(part.content)
        assert "PARTIAL.txt" in zipfile.ZipFile(tmp_path / "p.zip").namelist()
        # resume with guidance: the Project Manager is told what happened and what the person said
        res = await c.post(f"/api/runs/{run_id}/resume", json={"guidance": "skip the flaky test"})
        assert res.status_code == 200
        again = await wait_done(c, run_id)
        assert again["meta"]["status"] == "escalated"  # the demo QA still fails in this scenario
        evs = await events_of(c, run_id)
        assert "run_resumed" in [e["type"] for e in evs]
        seqs = [e["seq"] for e in evs]
        assert seqs == sorted(set(seqs))  # sequence numbers continue across the resume
        assert len(again["tasks"]) > len(info["tasks"])  # the earlier delegations are kept and new ones added


async def test_one_run_at_a_time_per_project_and_input_validation(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        assert (await c.post("/api/runs", json={"request": "x", "project": "../evil"})).status_code == 400
        assert (await c.post("/api/runs", json={"request": ""})).status_code == 422
        await c.post("/api/runs", json={"request": "a", "project": "shared"})  # waits for approval, so it stays active
        assert (await c.post("/api/runs", json={"request": "b", "project": "shared"})).status_code == 409
        other = await c.post("/api/runs", json={"request": "c", "final_review": False})  # a new project: no conflict
        assert other.status_code == 201
        assert (await c.get("/api/runs/zzzzzzzz")).status_code == 404
        assert (await c.get("/api/runs/00000000/artifacts/../../x")).status_code in (404, 422)


async def test_list_and_artifacts_and_cancel(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "list me", "final_review": False})).json()["run_id"]
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


@pytest.mark.parametrize(("scenario", "status"), [("recover", "passed"), ("escalate", "escalated")])
async def test_demo_model_drives_the_team_without_a_server(tmp_path, scenario, status):
    from agent.tools.workspace import Workspace

    from orchestrator.config import RunConfig
    from orchestrator.events import EventLog
    from orchestrator.runner import run_graph
    from orchestrator.task import TaskLog

    ws = Workspace(tmp_path, "d")
    ws.create()
    state = {"request": "r", "workspace": ws, "run_id": "r1", "model": DemoModel(delay=0, scenario=scenario),
             "task_log": TaskLog("r1", "r", []), "events": EventLog(), "config": RunConfig(concurrency=3)}
    result = await run_graph(state)
    assert result["status"] == status


class CodeAwareSandbox:
    """A sandbox that exits with the code the command itself asks for (`sys.exit(N)`), like the real one would."""

    def __init__(self):
        self.runs: list[list[str]] = []

    async def create_session(self, workspace, services):
        return {"id": "s1", "workspace": workspace, "services": [], "previews": []}

    async def delete_session(self, sid):
        pass

    async def close(self):
        pass

    async def job(self, sid, spec):
        self.runs.append(spec["cmd"])
        code = 1 if "sys.exit(1)" in spec["cmd"][-1] else 0
        yield {"type": "output", "stream": "stdout", "text": "1 failed\n" if code else "2 passed\n"}
        yield {"type": "exit", "code": code, "timed_out": False, "oom_killed": False, "duration_s": 0.1}


async def test_qa_runs_its_tests_in_the_sandbox_and_its_verdict_follows_the_real_exit_code(tmp_path):
    from agent.tools.workspace import Workspace

    from orchestrator.config import RunConfig
    from orchestrator.events import EventLog
    from orchestrator.runner import run_graph
    from orchestrator.task import TaskLog

    ws = Workspace(tmp_path, "d")
    ws.create()
    sandbox = CodeAwareSandbox()
    events = EventLog()
    state = {"request": "r", "workspace": ws, "run_id": "r1", "model": DemoModel(delay=0, real_tools=True),
             "sandbox_client": sandbox, "task_log": TaskLog("r1", "r", []), "events": events, "config": RunConfig(concurrency=2)}
    result = await run_graph(state)
    assert result["status"] == "passed" and len(sandbox.runs) == 2  # QA ran the tests twice: exit 1, then exit 0
    qa = [t for t in result["task_log"].tasks if t.role == "qa_engineer"]
    assert [(t.attempt, t.status, t.reason) for t in qa] == [(1, "fail", "tests failed"), (2, "pass", "tests passed")]
    run_tests = [e for e in events.since(0) if e["type"] == "tool_call" and e["tool"] == "run_tests"]
    assert len(run_tests) == 2


async def test_every_run_gets_its_own_project_so_a_zip_holds_only_that_run(tmp_path):
    """Found on a real run: runs shared one project, so a new request's zip also held every earlier run's files."""
    async with client_for(make_app(tmp_path)) as c:
        first = (await c.post("/api/runs", json={"request": "Make a calculator", "plan_approval": False, "final_review": False})).json()
        await wait_done(c, first["run_id"])
        # an old file from a previous run sits in the first project; the next run must not see it
        (tmp_path / first["project"] / "work" / "old_frontend.js").write_text("// from an earlier run\n")
        second = (await c.post("/api/runs", json={"request": "Create a calculator in python only", "plan_approval": False, "final_review": False})).json()
        await wait_done(c, second["run_id"])
        assert first["project"] != second["project"]
        assert second["project"].startswith("create-a-calculator-in-") and second["project"].endswith(second["run_id"])
        z = await c.get(f"/api/runs/{second['run_id']}/delivery.zip")
        (tmp_path / "second.zip").write_bytes(z.content)
        assert "old_frontend.js" not in zipfile.ZipFile(tmp_path / "second.zip").namelist()
        assert z.headers["content-disposition"].count(second["project"]) == 1  # the zip is named after its project


async def test_naming_an_existing_project_builds_on_its_files_on_purpose(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        first = (await c.post("/api/runs", json={"request": "Base", "plan_approval": False, "final_review": False})).json()
        await wait_done(c, first["run_id"])
        (tmp_path / first["project"] / "work" / "keep_me.txt").write_text("existing work\n")
        again = (await c.post("/api/runs", json={"request": "Add to it", "project": first["project"], "plan_approval": False, "final_review": False})).json()
        assert again["project"] == first["project"]
        await wait_done(c, again["run_id"])
        z = await c.get(f"/api/runs/{again['run_id']}/delivery.zip")
        (tmp_path / "again.zip").write_bytes(z.content)
        assert "keep_me.txt" in zipfile.ZipFile(tmp_path / "again.zip").namelist()


async def test_the_project_list_has_only_projects_with_runs_newest_first(tmp_path):
    (tmp_path / "some-other-tool-folder").mkdir()  # the volume is shared with other software
    async with client_for(make_app(tmp_path)) as c:
        a = (await c.post("/api/runs", json={"request": "alpha", "plan_approval": False, "final_review": False})).json()
        await wait_done(c, a["run_id"])
        b = (await c.post("/api/runs", json={"request": "beta", "plan_approval": False, "final_review": False})).json()
        await wait_done(c, b["run_id"])
        names = [p["name"] for p in (await c.get("/api/projects")).json()]
        assert names == [b["project"], a["project"]] and "some-other-tool-folder" not in names


def test_project_names_are_readable_and_valid():
    from orchestrator.runner import new_project_name
    from orchestrator.server import PROJECT_RE

    name = new_project_name("Create a calculator in python only it should have only arthemetic operators", "c5c38465")
    assert name == "create-a-calculator-in-p-c5c38465" or PROJECT_RE.match(name)
    assert PROJECT_RE.match(name) and name.endswith("-c5c38465") and len(name) <= 40
    assert new_project_name("!!!", "abcdef01") == "run-abcdef01"


async def review_pending(tmp_path: Path, run_id: str, round_no: int, timeout: float = 15) -> dict:
    """The review_requested event of a given round, read from the run's event file once it appears."""
    for _ in range(int(timeout / 0.05)):
        for path in tmp_path.glob(f"*/runs/{run_id}/events.jsonl"):
            for line in path.read_text().splitlines():
                event = json.loads(line)
                if event["type"] == "review_requested" and event["round"] == round_no:
                    return event
        await asyncio.sleep(0.05)
    raise AssertionError(f"no review round {round_no}")


async def test_the_run_pauses_for_a_final_review_and_builds_the_zip_only_after_acceptance(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "Add reset", "plan_approval": False})).json()["run_id"]
        review = await review_pending(tmp_path, run_id, 1)
        assert review["summary"] and "backend/app.py" in review["files"]  # what changed is listed for the person
        info = (await c.get(f"/api/runs/{run_id}")).json()
        assert info["meta"]["status"] == "running" and not info["has_zip"]  # nothing delivered yet
        assert (await c.post(f"/api/runs/{run_id}/review", json={"accept": True})).status_code == 200
        done = await wait_done(c, run_id)
        assert done["meta"]["status"] == "passed" and done["has_zip"]
        assert (await c.post(f"/api/runs/{run_id}/review", json={"accept": True})).status_code == 409  # no longer waiting
        kinds = [e["type"] for e in await events_of(c, run_id)]
        assert kinds.index("review_requested") < kinds.index("review_accepted") < kinds.index("delivery_ready")


async def test_asking_for_changes_sends_them_to_the_project_manager_and_asks_again(tmp_path):
    async with client_for(make_app(tmp_path)) as c:
        run_id = (await c.post("/api/runs", json={"request": "Add reset", "plan_approval": False})).json()["run_id"]
        await review_pending(tmp_path, run_id, 1)
        assert (await c.post(f"/api/runs/{run_id}/review", json={"accept": False})).status_code == 422  # must say what
        r = await c.post(f"/api/runs/{run_id}/review", json={"accept": False, "changes": "also reject reused tokens"})
        assert r.status_code == 200
        second = await review_pending(tmp_path, run_id, 2)
        assert second["summary"].startswith("The requested changes are made")
        await c.post(f"/api/runs/{run_id}/review", json={"accept": True})
        done = await wait_done(c, run_id)
        assert done["meta"]["status"] == "passed"
        assert any(t["objective"].startswith("Apply the requested changes") for t in done["tasks"])
        evs = await events_of(c, run_id)
        changes = next(e for e in evs if e["type"] == "review_changes_requested")
        assert changes["text"] == "also reject reused tokens"
        assert [e["round"] for e in evs if e["type"] == "review_requested"] == [1, 2]


async def test_a_run_that_did_not_pass_is_not_sent_for_review(tmp_path):
    async with client_for(make_app(tmp_path, scenario="escalate")) as c:
        run_id = (await c.post("/api/runs", json={"request": "x", "plan_approval": False})).json()["run_id"]
        info = await wait_done(c, run_id)
        assert info["meta"]["status"] == "escalated"
        assert "review_requested" not in [e["type"] for e in await events_of(c, run_id)]
