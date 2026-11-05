from orchestrator.roles import ALL_ROLES, load_role


def test_all_roles_load_with_nonempty_prompt_and_tools():
    assert len(ALL_ROLES) == 11
    assert ALL_ROLES[0] == "project_manager"
    for folder in ALL_ROLES:
        role = load_role(folder)
        assert role.folder == folder
        assert role.name and role.description
        assert len(role.tools) > 0
        assert 0 < len(role.prompt) < 2400  # the Project Manager's is the longest: it must be explicit for a small model


def test_project_manager_plans_and_delegates_but_cannot_write_files():
    role = load_role("project_manager")
    assert {"write_todos", "task", "read_file", "ls"} <= set(role.tools)
    assert "write_file" not in role.tools and "edit_file" not in role.tools


def test_qa_and_devops_reference_sandbox_tools():
    assert "run_tests" in load_role("qa_engineer").tools
    assert "run_build" in load_role("devops_engineer").tools
