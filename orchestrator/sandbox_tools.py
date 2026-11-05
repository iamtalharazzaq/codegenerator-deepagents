"""LangChain tool wrappers around codewright's SandboxClient, so roles like QA Engineer and
DevOps Engineer can actually run commands in a sandboxed container instead of just claiming they
did."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from agent.tools.sandbox import SandboxClient
from langchain_core.tools import BaseTool, tool


@dataclass(frozen=True)
class JobResult:
    output: str
    exit_code: int


async def run_job(client: SandboxClient, workspace: str, command: list[str]) -> JobResult:
    session = await client.create_session(workspace, [])
    sid = session["sid"]
    output_parts: list[str] = []
    exit_code = 0
    try:
        async for event in client.job(sid, {"command": command}):
            if event["type"] == "output":
                output_parts.append(event["data"])
            elif event["type"] == "exit":
                exit_code = event["code"]
    finally:
        # Each job gets its own session (an internal Docker network); never leave it behind.
        with contextlib.suppress(Exception):
            await client.delete_session(sid)
    return JobResult(output="".join(output_parts), exit_code=exit_code)


MAX_TOOL_OUTPUT = 4000  # the model's context is small; keep the tail, where failures are


def _format(result: JobResult) -> str:
    out = result.output
    if len(out) > MAX_TOOL_OUTPUT:
        out = "...(truncated)...\n" + out[-MAX_TOOL_OUTPUT:]
    return f"exit {result.exit_code}\n{out}"


def run_tests_tool(client: SandboxClient, workspace: str) -> BaseTool:
    """The workspace is bound here, so the model can only ever run commands on this project's own `work/`."""

    @tool("run_tests")
    async def run_tests(command: list[str]) -> str:
        """Run the project's test command in the sandbox and report its exit code and output."""
        return _format(await run_job(client, workspace, command))

    return run_tests


def run_build_tool(client: SandboxClient, workspace: str) -> BaseTool:
    @tool("run_build")
    async def run_build(command: list[str]) -> str:
        """Run the project's build command in the sandbox and report its exit code and output."""
        return _format(await run_job(client, workspace, command))

    return run_build


def sandbox_tools_for(role: str, client: SandboxClient, workspace: str) -> list[BaseTool]:
    """The sandbox tools a role gets, bound to one project's workspace. The single place later tasks look this up from."""
    if role == "qa_engineer":
        return [run_tests_tool(client, workspace)]
    if role == "devops_engineer":
        return [run_build_tool(client, workspace)]
    return []
