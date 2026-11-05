import pytest

from orchestrator.sandbox_tools import (
    JobResult,
    run_job,
    run_tests_tool,
    sandbox_tools_for,
)

JOB_KEYS = {"toolchain", "cmd", "workdir", "timeout_s"}
TOOLCHAINS = {"python", "go", "node", "cpp", "tools", "browser"}


class FakeSandboxClient:
    """Enforces the real runner's contract (`JobSpec`): `toolchain` + `cmd`, no `command`; events carry `text`/`code`.
    The old tool sent `{"command": ...}` and read `event["data"]`; a lenient fake let that pass for months."""

    def __init__(self, events):
        self._events = events
        self.created_with = None
        self.specs: list[dict] = []
        self.deleted: list[str] = []

    async def create_session(self, workspace, services):
        self.created_with = (workspace, services)
        return {"id": "s1", "workspace": workspace, "services": [], "previews": []}

    async def delete_session(self, sid):
        self.deleted.append(sid)

    async def job(self, sid, spec):
        assert spec.keys() <= JOB_KEYS and {"toolchain", "cmd"} <= spec.keys(), f"bad job spec: {spec}"
        assert spec["toolchain"] in TOOLCHAINS and isinstance(spec["cmd"], list) and spec["cmd"]
        self.specs.append(spec)
        for event in self._events:
            yield event


def out(text):
    return {"type": "output", "stream": "stdout", "text": text}


def done(code, **kw):
    return {"type": "exit", "code": code, "timed_out": False, "oom_killed": False, "duration_s": 0.1, **kw}


async def test_run_job_collects_output_and_exit_code_in_the_runners_format():
    client = FakeSandboxClient([{"type": "start", "cmd": ["pytest"]}, out("running tests\n"), out("2 passed\n"), done(0)])
    result = await run_job(client, "proj1", ["pytest"], toolchain="python")
    assert result == JobResult(output="running tests\n2 passed\n", exit_code=0)
    assert client.created_with == ("proj1", [])
    assert client.specs[0]["cmd"] == ["pytest"] and client.specs[0]["toolchain"] == "python"


async def test_run_job_reports_nonzero_exit_even_with_little_output():
    result = await run_job(FakeSandboxClient([done(1)]), "p", ["make", "build"])
    assert (result.exit_code, result.output) == (1, "")


async def test_timeouts_oom_and_truncation_are_reported_not_hidden():
    client = FakeSandboxClient([out("x"), {"type": "truncated", "after_bytes": 1}, done(137, timed_out=True, oom_killed=True)])
    text = await run_tests_tool(client, "p").ainvoke({"command": ["t"]})
    assert text.startswith("exit 137") and "timed out" in text and "out of memory" in text and "cut" in text


async def test_run_tests_tool_formats_pass_fail_in_its_output_and_binds_the_workspace():
    client = FakeSandboxClient([out("1 failed\n"), done(1)])
    tool = run_tests_tool(client, "proj1")
    text = await tool.ainvoke({"command": ["pytest"]})
    assert text.startswith("exit 1") and "1 failed" in text
    assert client.created_with == ("proj1", [])  # the orchestrator chose the workspace, not the model
    assert "workspace" not in tool.args and {"command", "toolchain"} <= tool.args.keys()


async def test_a_wrong_toolchain_or_empty_command_is_an_error_message_not_a_job():
    client = FakeSandboxClient([done(0)])
    tool = run_tests_tool(client, "p")
    assert (await tool.ainvoke({"command": ["x"], "toolchain": "cobol"})).startswith("Error: toolchain")
    assert (await tool.ainvoke({"command": []})).startswith("Error: command")
    assert client.specs == [] and client.deleted == []  # nothing reached the sandbox, no session was opened


async def test_run_job_deletes_its_session_even_when_the_job_raises():
    class Boom(FakeSandboxClient):
        async def job(self, sid, spec):
            raise RuntimeError("runner lost")
            yield  # pragma: no cover

    client = Boom([])
    with pytest.raises(RuntimeError):
        await run_job(client, "p", ["x"])
    assert client.deleted == ["s1"]


async def test_long_output_is_truncated_to_its_tail():
    client = FakeSandboxClient([out("x" * 10000 + "THE_FAILURE\n"), done(1)])
    text = await run_tests_tool(client, "p").ainvoke({"command": ["t"]})
    assert text.startswith("exit 1") and "THE_FAILURE" in text and len(text) < 4200


def test_sandbox_tools_for_maps_role_to_tools():
    client = FakeSandboxClient([])
    assert [t.name for t in sandbox_tools_for("qa_engineer", client, "p")] == ["run_tests"]
    assert [t.name for t in sandbox_tools_for("devops_engineer", client, "p")] == ["run_build"]
    assert sandbox_tools_for("backend_developer", client, "p") == []
