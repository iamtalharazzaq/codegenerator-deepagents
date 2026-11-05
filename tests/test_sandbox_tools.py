from orchestrator.sandbox_tools import JobResult, run_job, run_tests_tool


class FakeSandboxClient:
    def __init__(self, events):
        self._events = events
        self.created_with = None
        self.deleted: list[str] = []

    async def create_session(self, workspace, services):
        self.created_with = (workspace, services)
        return {"sid": "s1"}

    async def delete_session(self, sid):
        self.deleted.append(sid)

    async def job(self, sid, spec):
        for event in self._events:
            yield event


async def test_run_job_collects_output_and_exit_code():
    events = [{"type": "output", "data": "running tests\n"}, {"type": "output", "data": "2 passed\n"},
              {"type": "exit", "code": 0}]
    client = FakeSandboxClient(events)
    result = await run_job(client, "/work", ["pytest"])
    assert result == JobResult(output="running tests\n2 passed\n", exit_code=0)
    assert client.created_with == ("/work", [])


async def test_run_job_reports_nonzero_exit_even_with_little_output():
    client = FakeSandboxClient([{"type": "exit", "code": 1}])
    result = await run_job(client, "/work", ["make", "build"])
    assert result.exit_code == 1
    assert result.output == ""


async def test_run_tests_tool_formats_pass_fail_in_its_output():
    client = FakeSandboxClient([{"type": "output", "data": "1 failed\n"}, {"type": "exit", "code": 1}])
    tool = run_tests_tool(client, "proj1")
    text = await tool.ainvoke({"command": ["pytest"]})
    assert "exit 1" in text
    assert "1 failed" in text
    # The workspace is bound by the orchestrator: the model's arguments cannot choose it.
    assert client.created_with == ("proj1", [])
    assert "workspace" not in tool.args


async def test_run_job_deletes_its_session_even_when_the_job_raises():
    class Boom(FakeSandboxClient):
        async def job(self, sid, spec):
            raise RuntimeError("runner lost")
            yield  # pragma: no cover

    client = Boom([])
    try:
        await run_job(client, "p", ["x"])
    except RuntimeError:
        pass
    assert client.deleted == ["s1"]


async def test_long_output_is_truncated_to_its_tail():
    big = "x" * 10000 + "THE_FAILURE\n"
    client = FakeSandboxClient([{"type": "output", "data": big}, {"type": "exit", "code": 1}])
    text = await run_tests_tool(client, "p").ainvoke({"command": ["t"]})
    assert text.startswith("exit 1") and "THE_FAILURE" in text and len(text) < 4200


def test_sandbox_tools_for_maps_role_to_tools():
    from orchestrator.sandbox_tools import sandbox_tools_for

    client = FakeSandboxClient([])
    assert [t.name for t in sandbox_tools_for("qa_engineer", client, "p")] == ["run_tests"]
    assert [t.name for t in sandbox_tools_for("devops_engineer", client, "p")] == ["run_build"]
    assert sandbox_tools_for("backend_developer", client, "p") == []
