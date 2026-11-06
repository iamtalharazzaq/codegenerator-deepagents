"""LangChain tool wrappers around codewright's SandboxClient, so roles like QA Engineer and
DevOps Engineer can actually run commands in a sandboxed container instead of just claiming they
did."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent.tools.sandbox import SandboxClient
from langchain_core.tools import BaseTool, tool

TOOLCHAINS = ("python", "node", "go", "cpp", "tools")  # the runner also has "browser"; not for tests or builds
JOB_TIMEOUT_S = 300
MAX_TOOL_OUTPUT = 4000  # the model's context is small; keep the tail, where failures are


# Commands that destroy data, publish, or change real infrastructure never run on a specialist's say-so: the person
# approves each one (`confirm`), and without a way to ask they are refused. The check is on the command text.
SENSITIVE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-\w*[rf]|\brm\s+--(recursive|force)"), "deletes files"),
    (re.compile(r"\b(drop|truncate)\s+(table|database|schema)\b", re.IGNORECASE), "destroys database data"),
    (re.compile(r"\bgit\s+(push|reset\s+--hard|clean\s+-\w*f)"), "pushes or discards git history"),
    (re.compile(r"\b(terraform\s+(apply|destroy)|kubectl\s+(apply|delete)|helm\s+(install|upgrade|uninstall))\b"), "changes real infrastructure"),
    (re.compile(r"\b(docker\s+push|npm\s+publish|twine\s+upload|cargo\s+publish)\b"), "publishes a package or image"),
    (re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash)\b"), "runs a downloaded script"),
)
# Asked before a sensitive command runs: (what makes it sensitive, the command) -> whether the person approved.
ConfirmFn = Callable[[str, list[str]], Awaitable[bool]]


def sensitive_reason(command: list[str]) -> str | None:
    text = " ".join(command)
    return next((why for pattern, why in SENSITIVE if pattern.search(text)), None)


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


async def _run(
    client: SandboxClient, workspace: str, command: list[str], toolchain: str, workdir: str, confirm: ConfirmFn | None
) -> str:
    if toolchain not in TOOLCHAINS:
        return f"Error: toolchain must be one of {', '.join(TOOLCHAINS)}."
    if not command:
        return "Error: command must not be empty."
    if (why := sensitive_reason(command)) is not None and not (confirm is not None and await confirm(why, command)):
        return (
            f"Not run: this command {why}, and the person did not approve it (or could not be asked). "
            "Do not try to get around this: pick a safe alternative, or report the task as blocked."
        )
    return _format(await run_job(client, workspace, command, toolchain=toolchain, workdir=workdir))


# What the model is shown for the two tools (the docstrings below are longer; see `orchestrator/lean.py`).
SANDBOX_TEXT = {
    "run_tests": 'Run a test command in the sandbox; returns its real exit code and output. command is a list, e.g. ["pytest", "-q"]; toolchain is python, node, go, cpp or tools.',
    "run_build": 'Run a build command in the sandbox; returns its real exit code and output. command is a list, e.g. ["npm", "run", "build"]; toolchain is python, node, go, cpp or tools.',
}


def run_tests_tool(client: SandboxClient, workspace: str, confirm: ConfirmFn | None = None) -> BaseTool:
    """The workspace is bound here, so the model can only ever run commands on this project's own `work/`."""

    @tool("run_tests")
    async def run_tests(command: list[str], toolchain: str = "python", workdir: str = ".") -> str:
        """Run the project's test command in the sandbox (toolchain: python, node, go, cpp or tools) and report its
        real exit code and output. Example: command ["pytest", "-q"], toolchain "python"."""
        return await _run(client, workspace, command, toolchain, workdir, confirm)

    return run_tests


def run_build_tool(client: SandboxClient, workspace: str, confirm: ConfirmFn | None = None) -> BaseTool:
    @tool("run_build")
    async def run_build(command: list[str], toolchain: str = "python", workdir: str = ".") -> str:
        """Run the project's build command in the sandbox (toolchain: python, node, go, cpp or tools) and report its
        real exit code and output. Example: command ["npm", "run", "build"], toolchain "node"."""
        return await _run(client, workspace, command, toolchain, workdir, confirm)

    return run_build


def sandbox_tools_for(role: str, client: SandboxClient, workspace: str, confirm: ConfirmFn | None = None) -> list[BaseTool]:
    """The sandbox tools a role gets, bound to one project's workspace. The single place later tasks look this up from."""
    if role == "qa_engineer":
        return [run_tests_tool(client, workspace, confirm)]
    if role == "devops_engineer":
        return [run_build_tool(client, workspace, confirm)]
    return []
