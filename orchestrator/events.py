"""Append-only event log for a run (`runs/<run_id>/events.jsonl`).

Every step of the loop emits an event, so a UI (or a human with `tail -f`) never has to guess what
the loop is doing. Events are plain JSON objects: `{"seq", "ts", "type", ...data}`. `seq` is
monotonic per run and continues across a resume.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

Event = dict[str, Any]


class EventLog:
    def __init__(self, path: Path | None = None, on_emit: Callable[[Event], None] | None = None) -> None:
        self.path = path
        self._on_emit = on_emit
        self._events: list[Event] = []
        self._subscribers: list[asyncio.Queue[Event]] = []
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._events.append(json.loads(line))
        self._seq = self._events[-1]["seq"] if self._events else 0

    def emit(self, type: str, **data: Any) -> Event:
        self._seq += 1
        event: Event = {"seq": self._seq, "ts": round(time.time(), 3), "type": type, **data}
        self._events.append(event)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        if self._on_emit is not None:
            self._on_emit(event)
        return event

    def since(self, seq: int = 0) -> list[Event]:
        return [e for e in self._events if e["seq"] > seq]

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    @property
    def last_type(self) -> str | None:
        return self._events[-1]["type"] if self._events else None
