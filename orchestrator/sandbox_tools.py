"""LangChain tool wrappers around codewright's SandboxClient, so roles like QA Engineer and
DevOps Engineer can actually run commands in a sandboxed container instead of just claiming they
did."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from agent.tools.sandbox import SandboxClient
from langchain_core.tools import BaseTool, tool

TOOLCHAINS = ("python", "node", "go", "cpp", "tools")  # the runner also has "browser"; not for tests or builds
JOB_TIMEOUT_S = 300
MAX_TOOL_OUTPUT = 4000  # the model's context is small; keep the tail, where failures are


@dataclass(frozen=True)
class JobResult:
    output: str
    exit_code: int
    note: str = ""


async def run_job(
    client: SandboxClient, workspace: str, command: list[str], *, toolchain: str = "python", workdir: str = "."
) -> JobResult:
    """Run one command in the project's sandbox and collect its output and real exit code.

    The request follows the runner's `JobSpec` (`toolchain`, `cmd`, `workdir`...); its events are
    `start`, `output` (field `text`), `truncated`, and `exit` (`code`, `timed_out`, `oom_killed`)."""
    session = await client.create_session(workspace, [])
    sid = session["id"]  # the runner's session dict (`as_dict()`) names it "id"
    output_parts: list[str] = []
    exit_code = 0
    notes: list[str] = []
    try:
        spec = {"toolchain": toolchain, "cmd": command, "workdir": workdir, "timeout_s": JOB_TIMEOUT_S}
        async for event in client.job(sid, spec):
            kind = event.get("type")
            if kind == "output":
                output_parts.append(event["text"])
            elif kind == "truncated":
                notes.append("(output was cut)")
            elif kind == "exit":
                exit_code = int(event["code"])
                if event.get("timed_out"):
                    notes.append(f"(timed out after {JOB_TIMEOUT_S}s)")
                if event.get("oom_killed"):
                    notes.append("(ran out of memory)")
    finally:
        # Each job gets its own session (an internal Docker network); never leave it behind.
        with contextlib.suppress(Exception):
            await client.delete_session(sid)
    return JobResult(output="".join(output_parts), exit_code=exit_code, note=" ".join(notes))


def _format(result: JobResult) -> str:
    out = result.output
    if len(out) > MAX_TOOL_OUTPUT:
        out = "...(truncated)...\n" + out[-MAX_TOOL_OUTPUT:]
    head = f"exit {result.exit_code}" + (f" {result.note}" if result.note else "")
    return f"{head}\n{out}"


async def _run(client: SandboxClient, workspace: str, command: list[str], toolchain: str, workdir: str) -> str:
    if toolchain not in TOOLCHAINS:
        return f"Error: toolchain must be one of {', '.join(TOOLCHAINS)}."
    if not command:
        return "Error: command must not be empty."
    return _format(await run_job(client, workspace, command, toolchain=toolchain, workdir=workdir))


def run_tests_tool(client: SandboxClient, workspace: str) -> BaseTool:
    """The workspace is bound here, so the model can only ever run commands on this project's own `work/`."""

    @tool("run_tests")
    async def run_tests(command: list[str], toolchain: str = "python", workdir: str = ".") -> str:
        """Run the project's test command in the sandbox (toolchain: python, node, go, cpp or tools) and report its
        real exit code and output. Example: command ["pytest", "-q"], toolchain "python"."""
        return await _run(client, workspace, command, toolchain, workdir)

    return run_tests


def run_build_tool(client: SandboxClient, workspace: str) -> BaseTool:
    @tool("run_build")
    async def run_build(command: list[str], toolchain: str = "python", workdir: str = ".") -> str:
        """Run the project's build command in the sandbox (toolchain: python, node, go, cpp or tools) and report its
        real exit code and output. Example: command ["npm", "run", "build"], toolchain "node"."""
        return await _run(client, workspace, command, toolchain, workdir)

    return run_build


def sandbox_tools_for(role: str, client: SandboxClient, workspace: str) -> list[BaseTool]:
    """The sandbox tools a role gets, bound to one project's workspace. The single place later tasks look this up from."""
    if role == "qa_engineer":
        return [run_tests_tool(client, workspace)]
    if role == "devops_engineer":
        return [run_build_tool(client, workspace)]
    return []
