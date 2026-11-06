"""Lean tool text for the model: the context window is small (4096 tokens), and deepagents' tools arrive with long
generic descriptions and per-argument prose that cost about a third of it before any work starts.

`LeanTools` changes only what the model *sees* (the tool list of each model call): a short description, and the
argument schema without its prose. The tool node keeps the original tools, so execution and validation are unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

# Replacements for deepagents' filesystem tool descriptions (about 3,000 characters in all).
FILE_TOOLS = {
    "ls": "List the files in a directory.",
    "read_file": "Read a file (100 lines at a time; use offset and limit to see more). Read before you edit.",
    "write_file": "Create a file with the given content.",
    "edit_file": "Replace old_string with new_string in a file you have read.",
    "delete_file": "Delete one file (only inside your WRITES scope).",
}


def task_tool_text(roster: dict[str, str]) -> str:
    """The `task` tool's description: who can be asked, and how, in a few lines (deepagents' own is about 2,000)."""
    lines = "\n".join(f"- {name}: {text}" for name, text in roster.items())
    return (
        "Hand one piece of work to a specialist and get its reply. subagent_type is one of:\n"
        f"{lines}\n"
        "The specialist sees only `description`, so put the whole instruction there. "
        "Several calls in one message run side by side."
    )


def _strip_prose(node: Any) -> Any:
    """A JSON schema without its titles and descriptions: the argument names and types are what the model needs."""
    if isinstance(node, dict):
        return {k: _strip_prose(v) for k, v in node.items() if k not in ("title", "description") or isinstance(v, dict)}
    if isinstance(node, list):
        return [_strip_prose(v) for v in node]
    return node


def first_sentence(text: str) -> str:
    flat = " ".join(text.split())
    return re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]


def lean(tool: Any, description: str | None = None) -> Any:
    """A copy of `tool` that tells the model less. Anything that is not a LangChain tool is left alone."""
    if not isinstance(tool, BaseTool):
        return tool
    schema = _strip_prose(convert_to_openai_tool(tool)["function"].get("parameters", {}))
    return tool.model_copy(update={"description": description or first_sentence(tool.description), "args_schema": schema})


class LeanTools(AgentMiddleware[Any, Any, Any]):
    """Shows the model lean versions of the tools. `descriptions` maps a tool name to its short text; tools not named
    keep the first sentence of their description and lose their argument prose."""

    def __init__(self, descriptions: dict[str, str]) -> None:
        super().__init__()
        self.descriptions = descriptions

    @property
    def name(self) -> str:
        return "LeanTools"

    def _lean(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        return request.override(tools=[lean(t, self.descriptions.get(getattr(t, "name", ""))) for t in request.tools])

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]]
    ) -> Any:
        return await handler(self._lean(request))

    def wrap_model_call(self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]) -> Any:
        return handler(self._lean(request))
