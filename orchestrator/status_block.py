"""Parser for the structured status block that sub-agent artifacts end with.

This is the core anti-silent-failure mechanism: every sub-agent's artifact
must end with a block like:

    ---
    status: pass
    reason: one line
    ---

Done-condition checks parse this block as code, never trust prose. A missing
block always defaults to ``fail``.

Standalone, pure-function module: no dependency on any other part of the
orchestrator package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_STATUS_BLOCK_RE = re.compile(
    r"^---\nstatus:\s*(pass|fail)\s*\nreason:\s*(.+?)\s*\n---$",
    re.MULTILINE,
)


# Small models often wrap the block in a code fence instead of writing the `---` lines. That is still a structured
# block with explicit keys, so it is accepted, but only as the very last thing in the reply (never from the middle).
_FENCED_END_RE = re.compile(
    r"(?:^|\n)```[A-Za-z]*\n\s*status:\s*(pass|fail)\s*\nreason:\s*(.+?)\s*\n```\s*\Z",
)


# Another slip seen with the real model: the opening `---`, `status:` and `reason:` are there but the closing `---` is
# forgotten. Accepted only when it is the very last thing in the reply.
_UNCLOSED_END_RE = re.compile(r"(?:^|\n)---\nstatus:\s*(pass|fail)\s*\nreason:\s*([^\n]+?)\s*\Z")


@dataclass(frozen=True)
class StatusResult:
    status: Literal["pass", "fail"]
    reason: str


def parse_status(text: str) -> StatusResult:
    """Parse the last status block found in ``text``.

    Returns StatusResult("fail", "no status block found in the artifact")
    when no block is present.
    """
    fenced = _FENCED_END_RE.search(text)
    if fenced is not None:
        return StatusResult(fenced.group(1), fenced.group(2))  # type: ignore[arg-type]
    unclosed = _UNCLOSED_END_RE.search(text)
    if unclosed is not None:
        return StatusResult(unclosed.group(1), unclosed.group(2))  # type: ignore[arg-type]
    matches = list(_STATUS_BLOCK_RE.finditer(text))
    if not matches:
        return StatusResult("fail", "no status block found in the artifact")

    last = matches[-1]
    status = last.group(1)
    reason = last.group(2)
    assert status in ("pass", "fail")
    return StatusResult(status, reason)  # type: ignore[arg-type]
