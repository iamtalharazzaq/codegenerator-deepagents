import pytest

from orchestrator.guardrails import (
    AgentStuck,
    CallTracker,
    WriteScope,
    normalize_path,
    path_matches,
    tool_refusal,
)


def test_normalize_path_rejects_escape():
    assert normalize_path("/src/app.py") == "src/app.py"
    assert normalize_path("src/./app.py") == "src/app.py"
    assert normalize_path("../etc/passwd") is None
    assert normalize_path("/a/../../b") is None


def test_scope_blocks_outside_globs_git_env_and_escape():
    scope = WriteScope(globs=("backend/**",))
    assert scope.check("/backend/app.py", 10) is None
    assert "outside" in scope.check("/frontend/app.js", 10)
    assert ".git" in scope.check("/backend/.git/config", 10)
    assert ".env" in scope.check("/backend/.env", 10)
    assert scope.check("/backend/.env.example", 10) is None
    assert "escapes" in scope.check("../x", 10)


def test_scope_with_no_globs_allows_anywhere_but_still_blocks_forbidden():
    scope = WriteScope()
    assert scope.check("/anything/here.txt", 5) is None
    assert scope.check("/.git/HEAD", 5) is not None


def test_scope_enforces_file_size_and_count_budgets():
    scope = WriteScope(max_file_bytes=10, max_files=2)
    assert "bytes" in scope.check("/a.txt", 11)
    for name in ("/a.txt", "/b.txt"):
        assert scope.check(name, 1) is None
        scope.record(name)
    assert "files" in scope.check("/c.txt", 1)
    assert scope.check("/a.txt", 1) is None  # rewriting a file already written is not a new file


def test_path_matches_directory_globs_do_not_leak_to_sibling_prefixes():
    assert path_matches("src/api/x.py", ("src/api/**",))
    assert not path_matches("src/api2/x.py", ("src/api/**",))
    assert path_matches("README.md", ("*.md",))
    assert path_matches("docs/design.md", ("docs/design.md",))


def test_tool_refusal_covers_writes_and_the_git_folder():
    scope = WriteScope(globs=("backend/**",))
    assert tool_refusal(scope, "write_file", {"file_path": "/backend/a.py", "content": "x"}) is None
    assert "backend/a.py" in scope.written
    path, reason = tool_refusal(scope, "write_file", {"file_path": "/other/a.py", "content": "x"})
    assert path == "/other/a.py" and "outside" in reason
    assert tool_refusal(scope, "edit_file", {"file_path": "/backend/a.py", "new_string": "y"}) is None
    # reads may roam the project, except .git (a blocked agent was seen listing every object folder in it)
    assert tool_refusal(scope, "ls", {"path": "/docs"}) is None
    assert tool_refusal(scope, "read_file", {"file_path": "/.github/workflows/ci.yml"}) is None  # ".github" is not ".git"
    for name, args in [("ls", {"path": "/.git"}), ("ls", {"path": "/.git/objects/29"}), ("read_file", {"file_path": ".git/HEAD"}),
                       ("grep", {"path": "/.git/refs", "pattern": "x"})]:
        assert tool_refusal(scope, name, args)[1] == "the .git folder is not available"


def test_call_tracker_stops_repeats_and_runaway_tasks():
    tracker = CallTracker(max_calls=50)
    for _ in range(3):
        tracker.note("read_file", {"file_path": "/a"})
    with pytest.raises(AgentStuck, match="repeated the same read_file call 4 times"):
        tracker.note("read_file", {"file_path": "/a"})
    capped = CallTracker(max_calls=3)
    for i in range(3):
        capped.note("ls", {"path": f"/d{i}"})
    with pytest.raises(AgentStuck, match="more than 3 tool calls"):
        capped.note("ls", {"path": "/d9"})
