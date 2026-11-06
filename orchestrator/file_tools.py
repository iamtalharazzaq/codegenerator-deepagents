"""File tools of our own, for what deepagents' filesystem tools cannot do. Today: deleting a file.

Without this, a request like "remove the HTML file" could not be done by anyone on the team. The tool is bound to one
project's folder, and the specialist guard (`SubAgentGuard`) checks the path against the task's `WRITES` scope first,
exactly as for `write_file`.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool, tool

from orchestrator.guardrails import normalize_path


def delete_file_tool(work: Path) -> BaseTool:
    root = work.resolve()

    @tool("delete_file")
    def delete_file(file_path: str) -> str:
        """Delete one file from the project. Only files inside your WRITES scope can be deleted."""
        rel = normalize_path(file_path)
        if not rel:
            return "Error: give the path of a file."
        target = root / rel
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            return "Error: that path is outside the project."
        if not target.is_file():
            return f"Error: {rel} is not a file in the project (nothing was deleted)."
        target.unlink()
        return f"Deleted {rel}"

    return delete_file


def file_tools_for(allowed: tuple[str, ...], work: Path) -> list[BaseTool]:
    """Our own file tools that a role's tool list names."""
    return [delete_file_tool(work)] if "delete_file" in allowed else []
