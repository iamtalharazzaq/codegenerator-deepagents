"""Role loader: each sub-agent role has its own prompt and tool allowlist.

Prompts live in `orchestrator/agents/<role>/prompt.md` and the allowlist in `config.yaml`
alongside it. Mirrors codewright's `agent/agents/base.py::load_role` shape, but points at this
project's own `orchestrator/agents/` directory — these roles are this project's own files, not
codewright's.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROLES_DIR = Path(__file__).resolve().parent / "agents"

ALL_ROLES: tuple[str, ...] = (
    "project_manager",
    "business_analyst",
    "product_manager",
    "solution_architect",
    "code_analyst",
    "database_engineer",
    "backend_developer",
    "frontend_developer",
    "ui_ux_designer",
    "qa_engineer",
    "devops_engineer",
)


@dataclass(frozen=True)
class RoleConfig:
    folder: str
    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str


@cache
def load_role(folder: str) -> RoleConfig:
    base = ROLES_DIR / folder
    config = yaml.safe_load((base / "config.yaml").read_text(encoding="utf-8"))
    return RoleConfig(
        folder=folder,
        name=config["name"],
        description=config["description"],
        tools=tuple(config["tools"]),
        prompt=(base / "prompt.md").read_text(encoding="utf-8").strip(),
    )
