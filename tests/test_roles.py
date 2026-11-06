from orchestrator.roles import (
    ALL_ROLES,
    PLANNER_ROLE,
    describe_team,
    load_role,
    specialists,
)


def test_all_roles_load_with_nonempty_prompt_and_tools():
    assert len(ALL_ROLES) == 13
    assert ALL_ROLES[0] == "project_manager"
    for folder in ALL_ROLES:
        role = load_role(folder)
        assert role.folder == folder
        assert role.name and role.description
        assert len(role.tools) > 0
        assert 0 < len(role.prompt) < 3200  # the Project Manager's is the longest: it must be explicit for a small model


def test_project_manager_plans_and_delegates_but_cannot_write_files():
    role = load_role("project_manager")
    assert {"write_todos", "task", "read_file", "ls"} <= set(role.tools)
    assert "write_file" not in role.tools and "edit_file" not in role.tools


def test_qa_and_devops_reference_sandbox_tools():
    assert "run_tests" in load_role("qa_engineer").tools
    assert "run_build" in load_role("devops_engineer").tools


def test_registry_is_discovered_from_the_agent_folders_with_capabilities():
    assert {"security_engineer", "technical_writer"} <= set(ALL_ROLES)
    assert PLANNER_ROLE not in specialists()
    for folder in specialists():
        assert load_role(folder).capabilities, f"{folder} has no capabilities"


def test_describe_team_finds_specialists_by_capability_not_by_name():
    assert "database-engineer" in describe_team("schema")
    assert "qa-engineer" in describe_team("test execution")
    assert "security-engineer" in describe_team("threat")
    assert "technical-writer" in describe_team("readme")
    assert describe_team("").count("\n") == len(specialists()) - 1
    assert "No specialist matches" in describe_team("quantum")


def test_the_solution_architect_is_asked_for_a_high_level_design_in_a_fixed_outline_scaled_to_the_request():
    prompt = load_role("solution_architect").prompt
    sections = ["Overview", "Main parts", "How it fits together", "Data", "Interfaces", "Tech stack", "Decisions and risks"]
    positions = [prompt.index(f"{n}. {name}") for n, name in enumerate(sections, start=1)]
    assert positions == sorted(positions)
    assert "HIGH level" in prompt and "Size the design to the request" in prompt
    assert "no code, no class or function lists, no field-level schemas" in prompt
    assert "high-level design" in describe_team("high-level design")
