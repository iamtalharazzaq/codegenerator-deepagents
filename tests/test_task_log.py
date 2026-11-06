from pathlib import Path

from orchestrator.task import Task, TaskLog, load_task_log, save_task_log, unresolved


def test_round_trips_through_json(tmp_path: Path):
    log = TaskLog(run_id="r1", request="add a wishlist", tasks=[
        Task(id="t1", role="product_manager", objective="write stories", status="pending", attempt=1,
             depends_on=("t0",), acceptance=("stories.md exists",), evidence=["wrote 1 file(s): stories.md"]),
    ])
    path = tmp_path / "task-log.json"
    save_task_log(log, path)
    loaded = load_task_log(path)
    assert loaded == log


def test_updating_a_task_status_persists(tmp_path: Path):
    log = TaskLog(run_id="r1", request="x", tasks=[
        Task(id="t1", role="qa_engineer", objective="test"),
    ])
    path = tmp_path / "task-log.json"
    save_task_log(log, path)
    loaded = load_task_log(path)
    loaded.tasks[0].status = "fail"
    loaded.tasks[0].attempt = 1
    save_task_log(loaded, path)
    reloaded = load_task_log(path)
    assert reloaded.tasks[0].status == "fail"
    assert reloaded.tasks[0].attempt == 1


def test_a_log_written_by_an_older_version_still_loads(tmp_path: Path):
    path = tmp_path / "task-log.json"
    path.write_text(
        '{"run_id": "r1", "request": "x", "last_failure": null, "tasks": [{"id": "t1", "role": "qa_engineer", "objective": "o",'
        ' "inputs": [], "done_condition": "d", "status": "pass", "attempt": 2, "depends_on": [], "writes": ["a/**"],'
        ' "reason": "", "reasons": []}]}'
    )
    task = load_task_log(path).tasks[0]
    assert (task.id, task.status, task.attempt, task.writes, task.evidence) == ("t1", "pass", 2, ("a/**",), [])


def test_failed_work_is_resolved_by_a_passing_retry_or_a_later_pass_of_the_same_specialist():
    def mk(id_, role, status, retry_of=""):
        return Task(id=id_, role=role, objective="o", status=status, retry_of=retry_of)

    assert unresolved([mk("a", "qa", "fail"), mk("b", "qa", "pass", retry_of="a")]) == []
    assert unresolved([mk("a", "qa", "fail"), mk("b", "dev", "pass", retry_of="a")]) == []  # reassigned to another specialist
    assert unresolved([mk("a", "qa", "fail"), mk("b", "dev", "pass")]) != []  # unrelated pass fixes nothing
    chain = [mk("a", "qa", "fail"), mk("b", "qa", "fail", retry_of="a"), mk("c", "dev", "pass", retry_of="b")]
    assert unresolved(chain) == []
    assert [t.id for t in unresolved([mk("a", "qa", "fail"), mk("b", "qa", "fail", retry_of="a")])] == ["a", "b"]
