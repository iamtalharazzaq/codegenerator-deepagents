"""Independent check of a specialist's claimed result.

A specialist ends its reply with `status: pass`, but that is a claim. Before a pass is accepted, this looks at what
code observed while the specialist worked, never at what it said:

- every file it wrote is on disk and not empty, and a specialist given a `WRITES` scope wrote at least one file in
  it (unless it has a check tool: re-running tests after a fix writes nothing, and its proof is the exit code);
- a specialist that has a check tool (QA's `run_tests`, DevOps's `run_build`) really ran it, and its last run
  exited 0. Without a sandbox the tool does not exist, and the pass is accepted but marked UNVERIFIED.

A claimed `fail` is never turned into a pass. Semantic review (does it meet the requirement?) is a task for another
specialist, which the Project Manager orders with `AFTER:`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CHECK_TOOLS = ("run_tests", "run_build")
_EXIT_RE = re.compile(r"\Aexit (-?\d+)")


# "calculator.py defines add, subtract(a, b) and divide" : the names a DONE line says a file defines are looked for in it.
DEFINES_RE = re.compile(
    r"(?P<file>[\w./-]+\.(?:py|js|jsx|ts|tsx|go|java|rb|rs|c|cpp|h|sh))\s+(?:defines?|contains?|has|exports?|implements?)\s+"
    r"(?:(?:the\s+)?(?:functions?|classes?|methods?)\b)?\s*:?\s*(?P<names>.+)", re.IGNORECASE,
)
STOP_RE = re.compile(r"\s+(?:that|which|with|so|where|and\s+(?:returns?|handles?|raises?))\b.*", re.IGNORECASE)


def check_acceptance(acceptance: tuple[str, ...], work: Path) -> tuple[list[str], list[str]]:
    """What code can verify of the DONE lines: a file that is said to define names really does. Returns (evidence, problems).
    A DONE line in any other form is left to the specialist and to the tests: it is never failed for being unclear."""
    evidence: list[str] = []
    problems: list[str] = []
    for line in acceptance:
        found = DEFINES_RE.search(line)
        if not found:
            continue
        path = work / found["file"]
        names_text = re.sub(r"\([^)]*\)", "", STOP_RE.sub("", found["names"]))
        names = [n.strip() for n in re.split(r",|\band\b", names_text) if re.fullmatch(r"[A-Za-z_]\w*", n.strip())]
        if not names:
            continue
        if not path.is_file():
            problems.append(f"DONE says {found['file']} defines {', '.join(names)}, but that file does not exist")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [n for n in names if not re.search(rf"\b{re.escape(n)}\b", text)]
        if missing:
            problems.append(f"DONE says {found['file']} defines {', '.join(missing)}, but it does not")
        else:
            evidence.append(f"DONE checked: {found['file']} defines {', '.join(names)}")
    return evidence, problems


@dataclass
class Verdict:
    accepted: bool
    evidence: list[str] = field(default_factory=list)
    problem: str = ""


def exit_code(tool_output: str) -> int | None:
    """The exit code a sandbox tool reports on its first line (`exit 0 ...`), or None when it is not a run result."""
    match = _EXIT_RE.match(tool_output.strip())
    return int(match.group(1)) if match else None


def evaluate(
    *, role_tools: tuple[str, ...], sandbox: bool, written: set[str], deleted: set[str], expected_writes: tuple[str, ...],
    check_runs: list[tuple[str, int]], work: Path, acceptance: tuple[str, ...] = (),
) -> Verdict:
    evidence: list[str] = []
    problems: list[str] = []
    files = sorted(written)
    if files:
        shown = ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
        evidence.append(f"wrote {len(files)} file(s): {shown}")
    missing = [p for p in files if not (work / p).is_file() or (work / p).stat().st_size == 0]
    if missing:
        problems.append(f"says it wrote {', '.join(missing[:3])}, but the file is missing or empty")
    gone = sorted(deleted)
    if gone:
        evidence.append(f"deleted {len(gone)} file(s): {', '.join(gone[:5])}")
    still_there = [p for p in gone if (work / p).exists()]
    if still_there:
        problems.append(f"says it deleted {', '.join(still_there[:3])}, but the file is still there")
    tool = next((t for t in CHECK_TOOLS if t in role_tools), None)
    if tool is None and expected_writes and not files and not gone and any(t in role_tools for t in ("write_file", "edit_file")):
        problems.append(f"wrote no file inside its scope ({', '.join(expected_writes)})")
    if tool is not None:
        runs = [code for name, code in check_runs if name == tool]
        if not sandbox:
            evidence.append(f"UNVERIFIED: {tool} is not available here (no sandbox), so nothing was run")
        elif not runs:
            problems.append(f"never ran {tool}")
        else:
            evidence.append(f"{tool} ran {len(runs)} time(s), last exit {runs[-1]}")
            if runs[-1] != 0:
                problems.append(f"the last {tool} exited {runs[-1]}")
    done_evidence, done_problems = check_acceptance(acceptance, work)
    return Verdict(not problems and not done_problems, evidence + done_evidence, "; ".join(problems + done_problems))
