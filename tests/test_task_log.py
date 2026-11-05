from pathlib import Path

from orchestrator.task import Task, TaskLog, load_task_log, save_task_log


def test_round_trips_through_json(tmp_path: Path):
    log = TaskLog(run_id="r1", request="add a wishlist", tasks=[
        Task(id="t1", role="product_manager", objective="write stories",
             inputs=(), done_condition="stories.md exists", status="pending", attempt=0),
    ])
    path = tmp_path / "task-log.json"
    save_task_log(log, path)
    loaded = load_task_log(path)
    assert loaded == log


def test_updating_a_task_status_persists(tmp_path: Path):
    log = TaskLog(run_id="r1", request="x", tasks=[
        Task(id="t1", role="qa_engineer", objective="test", inputs=(), done_condition="tests pass"),
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
