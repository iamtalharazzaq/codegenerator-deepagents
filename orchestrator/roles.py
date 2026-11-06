"""The agent registry: every folder under `orchestrator/agents/` that holds a `config.yaml` is an agent.

A role is its folder: `prompt.md` (system prompt) and `config.yaml` (name, description, tool allowlist, the
capabilities the Project Manager picks it by, and an `enabled` switch). Adding a specialist is adding a folder;
nothing else in the orchestrator names it. The Project Manager discovers who can do what with
`describe_team` (its `get_agent_capabilities` tool), not from a list in the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROLES_DIR = Path(__file__).resolve().parent / "agents"
PLANNER_ROLE = "project_manager"


@dataclass(frozen=True)
class RoleConfig:
    folder: str
    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str
    capabilities: tuple[str, ...] = ()
    enabled: bool = True
    # What the Project Manager chooses by (short on purpose: the context window is small).
    use_when: str = ""
    task_types: tuple[str, ...] = ()
    inputs: str = ""
    deliverables: str = ""
    restrictions: str = ""


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
        capabilities=tuple(config.get("capabilities", ())),
        enabled=bool(config.get("enabled", True)),
        use_when=str(config.get("use_when", "")),
        task_types=tuple(config.get("task_types", ())),
        inputs=str(config.get("inputs", "")),
        deliverables=str(config.get("deliverables", "")),
        restrictions=str(config.get("restrictions", "")),
    )


def discover_roles() -> tuple[str, ...]:
    """The Project Manager first, then every other agent folder in name order."""
    others = sorted(p.name for p in ROLES_DIR.iterdir() if (p / "config.yaml").is_file() and p.name != PLANNER_ROLE)
    return (PLANNER_ROLE, *others)


ALL_ROLES: tuple[str, ...] = discover_roles()


def specialists() -> tuple[str, ...]:
    """The enabled agents the Project Manager may delegate to."""
    return tuple(r for r in ALL_ROLES if r != PLANNER_ROLE and load_role(r).enabled)


def roster_line(folder: str) -> str:
    """The one line about a specialist that is always in the Project Manager's context: who, and when to pick it."""
    role = load_role(folder)
    return role.use_when or role.description


def describe_team(query: str = "", limit: int = 3) -> str:
    """With no query: one `name: use_when` line per enabled specialist. With a query: the full record (description,
    capabilities, task types, inputs, deliverables, tools, restrictions) of the `limit` best matches, ranked by how many
    of the query's words appear in the name, capabilities, task types or description."""
    words = [w for w in re.split(r"\W+", query.lower()) if w]
    if not words:
        return "\n".join(f"- {load_role(f).name}: {roster_line(f)}" for f in specialists())
    scored = []
    for folder in specialists():
        role = load_role(folder)
        text = " ".join((role.name, role.description, role.use_when, *role.capabilities, *role.task_types)).lower().replace("_", " ")
        if score := sum(w in text for w in words):
            scored.append((score, folder))
    if not scored:
        return f"No specialist matches {query!r}. Call get_agent_capabilities with no argument to list everyone."
    blocks = []
    for _, folder in sorted(scored, key=lambda item: -item[0])[:limit]:
        r = load_role(folder)
        blocks.append(
            f"- {r.name}: {r.description}\n  Capabilities: {', '.join(r.capabilities) or 'general'}. Task types: {', '.join(r.task_types) or 'any'}.\n"
            f"  Needs: {(r.inputs or 'the objective').rstrip('.')}. Delivers: {(r.deliverables or 'the files in WRITES').rstrip('.')}.\n"
            f"  Tools: {', '.join(r.tools)}. Will not: {(r.restrictions or 'work outside its role').rstrip('.')}."
        )
    return "\n".join(blocks)
