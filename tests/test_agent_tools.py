from pathlib import Path

import pytest

from geocentric.agent.tools import ToolContext, default_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def registry():
    return default_registry()


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace_dir=workspace)


def test_write_then_read_file(registry, workspace):
    write_result = registry.execute("write_file", {"path": "hello.py", "content": "print(1)"}, _ctx(workspace), "c1")
    assert "SUCCESS" in write_result.content
    assert (workspace / "hello.py").read_text() == "print(1)"

    read_result = registry.execute("read_file", {"path": "hello.py"}, _ctx(workspace), "c2")
    assert "print(1)" in read_result.content
    assert not read_result.is_error


def test_sandbox_escape_is_blocked(registry, workspace):
    result = registry.execute("read_file", {"path": "../outside.txt"}, _ctx(workspace), "c1")
    assert result.is_error
    assert "Sandbox escape" in result.content


def test_sandbox_escape_blocked_for_write(registry, workspace):
    result = registry.execute("write_file", {"path": "../../etc/passwd", "content": "x"}, _ctx(workspace), "c1")
    assert result.is_error


def test_run_command_executes_in_workspace(registry, workspace):
    (workspace / "marker.txt").write_text("present")
    result = registry.execute("run_command", {"command": "ls"}, _ctx(workspace), "c1")
    assert "marker.txt" in result.content


def test_grep_finds_matches(registry, workspace):
    (workspace / "a.py").write_text("def foo():\n    return 1\n")
    (workspace / "b.py").write_text("def bar():\n    return 2\n")
    result = registry.execute("grep", {"pattern": "def foo"}, _ctx(workspace), "c1")
    assert "a.py" in result.content
    assert "b.py" not in result.content


def test_unknown_tool_returns_error(registry, workspace):
    result = registry.execute("not_a_real_tool", {}, _ctx(workspace), "c1")
    assert result.is_error


def test_legacy_alias_resolves_to_canonical_name(registry):
    assert registry.resolve_name("run_shell") == "run_command"
    assert registry.resolve_name("search_files") == "grep"
    assert registry.resolve_name("nonexistent") is None


def test_native_tooldefs_cover_every_registered_tool(registry):
    tooldefs = registry.to_native_tooldefs()
    assert {t.name for t in tooldefs} == {s.name for s in registry.all_specs()}
    for tooldef in tooldefs:
        assert tooldef.parameters.get("type") == "object"


def test_write_file_requires_approval_but_read_does_not(registry):
    assert registry.get("write_file").requires_approval is True
    assert registry.get("read_file").requires_approval is False
