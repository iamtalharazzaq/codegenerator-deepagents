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


@dataclass(frozen=True)
class StatusResult:
    status: Literal["pass", "fail"]
    reason: str


def parse_status(text: str) -> StatusResult:
    """Parse the last status block found in ``text``.

    Returns StatusResult("fail", "no status block found in the artifact")
    when no block is present.
    """
    matches = list(_STATUS_BLOCK_RE.finditer(text))
    if not matches:
        return StatusResult("fail", "no status block found in the artifact")

    last = matches[-1]
    status = last.group(1)
    reason = last.group(2)
    assert status in ("pass", "fail")
    return StatusResult(status, reason)  # type: ignore[arg-type]
