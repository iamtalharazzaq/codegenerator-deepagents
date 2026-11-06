"""Few-shot examples for specialists: a small hand-written library, and a deterministic choice of at most three.

Each role may have `agents/<role>/examples.yaml`, a list of entries:

    - id: qa-tests-for-a-function     # recorded in the event log and the task log
      task_types: [write_tests]       # names from the role's `task_types` in config.yaml
      tags: [test, pytest]            # words that suggest this example fits
      for: first                      # first | retry | any (default any)
      task: "what the task looked like"
      good: "what a good reply or file looks like"
      avoid: "the usual mistake"      # optional

The choice uses only the role (the folder), the task's objective words, and whether the task is a retry:
- a task type scores 1 when any of its words appears in the objective, and so does each tag that appears;
- an example needs a score of at least 2 (two separate signals), and a `for: first` / `for: retry` example is used only
  for that kind of task;
- on a retry, a `for: retry` example scores 2 more;
- best score first (ties by id), as many as fit the token budget, never more than three. Nothing matches: nothing is added.
Examples are put in the task message, not in the system prompt, so the permanent instructions stay short.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

import yaml

from orchestrator.roles import ROLES_DIR

CHARS_PER_TOKEN = 3.5  # measured against the model's own prompt-token count (see docs/EXAMPLES-EVAL.md)
MAX_EXAMPLES = 3
HEADING = "Example of this kind of task (shape only; do not copy its content):"


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


@dataclass(frozen=True)
class Example:
    id: str
    task_types: tuple[str, ...]
    tags: tuple[str, ...]
    when: str  # first | retry | any
    task: str
    good: str
    avoid: str = ""

    def text(self) -> str:
        lines = [f"Task: {self.task.strip()}", f"Good: {self.good.strip()}"]
        if self.avoid:
            lines.append(f"Avoid: {self.avoid.strip()}")
        return "\n".join(lines)


@cache
def load_examples(folder: str) -> tuple[Example, ...]:
    path = ROLES_DIR / folder / "examples.yaml"
    if not path.is_file():
        return ()
    return tuple(
        Example(
            id=str(e["id"]), task_types=tuple(e.get("task_types", ())), tags=tuple(e.get("tags", ())),
            when=str(e.get("for", "any")), task=str(e["task"]), good=str(e["good"]), avoid=str(e.get("avoid", "")),
        )
        for e in yaml.safe_load(path.read_text(encoding="utf-8")) or []
    )


def words(text: str) -> set[str]:
    """Lower-case words with a plural 's' removed, so `tests` matches `test`."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text.lower())}


def score(example: Example, objective: str, retry: bool) -> int:
    if example.when == ("first" if retry else "retry"):
        return 0
    have = words(objective)
    total = sum(1 for t in example.task_types if words(t.replace("_", " ")) & have) + sum(1 for tag in example.tags if words(tag) <= have)
    return total + (2 if retry and example.when == "retry" and total else 0) if total >= 2 else 0


def select_examples(folder: str, objective: str, *, retry: bool = False, budget_tokens: int = 250) -> list[Example]:
    ranked = sorted(((score(e, objective, retry), e) for e in load_examples(folder)), key=lambda item: (-item[0], item[1].id))
    chosen: list[Example] = []
    used = estimate_tokens(HEADING)
    for points, example in ranked:
        cost = estimate_tokens(example.text())
        if points and len(chosen) < MAX_EXAMPLES and used + cost <= budget_tokens:
            chosen.append(example)
            used += cost
    return chosen


def format_examples(chosen: list[Example]) -> str:
    return "\n\n".join([HEADING, *(e.text() for e in chosen)]) if chosen else ""
