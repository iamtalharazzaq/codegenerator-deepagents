"""LangChain tool wrappers around codewright's SandboxClient, so roles like QA Engineer and
DevOps Engineer can actually run commands in a sandboxed container instead of just claiming they
did."""

from __future__ import annotations

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
    async for event in client.job(sid, {"command": command}):
        if event["type"] == "output":
            output_parts.append(event["data"])
        elif event["type"] == "exit":
            exit_code = event["code"]
    return JobResult(output="".join(output_parts), exit_code=exit_code)


def run_tests_tool(client: SandboxClient) -> BaseTool:
    @tool("run_tests")
    async def run_tests(workspace: str, command: list[str]) -> str:
        """Run the project's test command in the sandbox and report its exit code and output."""
        result = await run_job(client, workspace, command)
        return f"exit {result.exit_code}\n{result.output}"

    return run_tests


def run_build_tool(client: SandboxClient) -> BaseTool:
    @tool("run_build")
    async def run_build(workspace: str, command: list[str]) -> str:
        """Run the project's build command in the sandbox and report its exit code and output."""
        result = await run_job(client, workspace, command)
        return f"exit {result.exit_code}\n{result.output}"

    return run_build


def sandbox_tools_for(role: str, client: SandboxClient) -> list[BaseTool]:
    """The sandbox tools a role gets. The single place later tasks look this up from."""
    if role == "qa_engineer":
        return [run_tests_tool(client)]
    if role == "devops_engineer":
        return [run_build_tool(client)]
    return []
