import json
from pathlib import Path

from orchestrator.events import EventLog


def test_emit_appends_jsonl_with_monotonic_seq(tmp_path: Path):
    log = EventLog(tmp_path / "runs" / "r1" / "events.jsonl")
    a = log.emit("run_started", run="r1")
    b = log.emit("plan_started")
    assert (a["seq"], b["seq"]) == (1, 2)
    lines = (tmp_path / "runs" / "r1" / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["type"] for x in lines] == ["run_started", "plan_started"]


def test_seq_continues_after_reopening_the_log(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    EventLog(path).emit("a")
    again = EventLog(path)
    assert again.emit("b")["seq"] == 2
    assert [e["type"] for e in again.since(1)] == ["b"]


async def test_subscribers_receive_new_events(tmp_path: Path):
    log = EventLog(tmp_path / "e.jsonl")
    queue = log.subscribe()
    log.emit("x", n=1)
    assert (await queue.get())["n"] == 1
    log.unsubscribe(queue)
    log.emit("y")
    assert queue.empty()


def test_in_memory_log_without_a_path():
    log = EventLog()
    log.emit("a")
    assert log.last_type == "a"
