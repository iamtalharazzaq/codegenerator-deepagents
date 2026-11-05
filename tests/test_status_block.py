from orchestrator.status_block import parse_status


def test_parses_pass():
    text = "Wrote design.md.\n---\nstatus: pass\nreason: design covers all 3 stories\n---\n"
    result = parse_status(text)
    assert result.status == "pass"
    assert result.reason == "design covers all 3 stories"


def test_parses_fail():
    text = "---\nstatus: fail\nreason: 2 of 5 tests still red\n---"
    assert parse_status(text) == __import__("orchestrator.status_block", fromlist=["StatusResult"]).StatusResult("fail", "2 of 5 tests still red")


def test_missing_block_defaults_to_fail():
    result = parse_status("I wrote some files but forgot the status block.")
    assert result.status == "fail"
    assert "no status block" in result.reason.lower()


def test_uses_the_last_block_when_several_are_present():
    text = "---\nstatus: fail\nreason: draft\n---\nrevised.\n---\nstatus: pass\nreason: final\n---"
    assert parse_status(text).status == "pass"
