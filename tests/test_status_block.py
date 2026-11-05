from orchestrator.status_block import StatusResult, parse_status


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


def test_a_fenced_status_block_at_the_very_end_is_accepted():
    """Seen with the real 9B model: correct work, status written inside a code fence without the dashes."""
    text = "Created greet.py.\n```\nstatus: pass\nreason: greet.py created\n```"
    assert parse_status(text) == StatusResult("pass", "greet.py created")
    assert parse_status("x\n```text\nstatus: fail\nreason: broke\n```\n").status == "fail"


def test_a_fenced_block_that_is_not_the_last_thing_is_not_trusted():
    text = "```\nstatus: pass\nreason: ok\n```\nActually I also did more work afterwards."
    assert parse_status(text).status == "fail"  # no trailing block, so it defaults to fail


def test_no_block_and_prose_claims_still_fail():
    assert parse_status("All done, status: pass!").status == "fail"
    assert parse_status("```\nstatus: pass\n```").status == "fail"  # no reason line: not a block
