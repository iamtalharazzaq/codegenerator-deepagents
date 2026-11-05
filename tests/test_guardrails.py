from orchestrator.guardrails import (
    ToolRecord,
    WriteScope,
    machine_verdict,
    normalize_path,
    path_matches,
    writes_overlap,
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


def test_writes_overlap_is_conservative():
    assert writes_overlap((), ("a/**",))  # empty scope means anywhere
    assert writes_overlap(("backend/**",), ("backend/api/**",))
    assert not writes_overlap(("backend/**",), ("frontend/**",))
    assert writes_overlap(("**/*.py",), ("frontend/**",))  # a leading wildcard could be anywhere


def test_machine_verdict_uses_the_last_real_exit_code():
    assert machine_verdict("backend_developer", []) is None
    assert machine_verdict("qa_engineer", []) == (False, "run_tests was never run, so a pass cannot be trusted")
    ok = [ToolRecord("run_tests", {}, "exit 1\nfailed"), ToolRecord("run_tests", {}, "exit 0\nok")]
    assert machine_verdict("qa_engineer", ok) == (True, "run_tests exited 0")
    bad = [ToolRecord("run_tests", {}, "exit 0\nok"), ToolRecord("run_tests", {}, "exit 2\nboom")]
    assert machine_verdict("qa_engineer", bad) == (False, "run_tests exited 2")
    assert machine_verdict("devops_engineer", [ToolRecord("run_build", {}, "exit 0\n")]) == (True, "run_build exited 0")
    errored = [ToolRecord("run_tests", {}, "Blocked", error=True)]
    assert machine_verdict("qa_engineer", errored)[0] is False
