from pathlib import Path

import pytest

from geocentric.agent.tools import ToolContext, default_registry


@pytest.fixture
def registry():
    return default_registry()


@pytest.fixture
def sample_workspace(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "math_utils.py").write_text(
        "def add(a, b):\n    return a + b\n\n\nclass Calculator:\n    def multiply(self, a, b):\n        return a * b\n"
    )
    (tmp_path / "README.md").write_text("# Sample project\nDoes math things.\n")
    return tmp_path


def test_project_index_finds_python_symbols(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    result = registry.execute("project_index", {}, ctx, "c1")
    assert not result.is_error
    assert "files indexed" in result.content


def test_find_symbol_locates_function(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    registry.execute("project_index", {}, ctx, "c1")
    result = registry.execute("find_symbol", {"name": "add"}, ctx, "c2")
    assert "math_utils.py" in result.content
    assert "add" in result.content


def test_find_symbol_locates_class(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    result = registry.execute("find_symbol", {"name": "Calculator"}, ctx, "c1")
    assert "Calculator" in result.content
    assert "math_utils.py" in result.content


def test_find_symbol_missing_reports_not_found(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    result = registry.execute("find_symbol", {"name": "DoesNotExist123"}, ctx, "c1")
    assert not result.is_error


def test_outline_file_lists_symbols(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    result = registry.execute("outline_file", {"path": "pkg/math_utils.py"}, ctx, "c1")
    assert "add" in result.content
    assert "Calculator" in result.content


def test_semantic_search_ranks_relevant_file(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    result = registry.execute("semantic_search", {"query": "calculator multiply math"}, ctx, "c1")
    assert not result.is_error
    assert "math_utils.py" in result.content


def test_project_index_cache_reused_on_second_call(registry, sample_workspace):
    ctx = ToolContext(workspace_dir=sample_workspace)
    registry.execute("project_index", {}, ctx, "c1")
    second = registry.execute("project_index", {}, ctx, "c2")
    assert "reused from cache" in second.content


def test_legacy_aliases_resolve(registry):
    assert registry.resolve_name("embedding_index") == "semantic_search"
    assert registry.resolve_name("project_index") == "project_index"
    assert registry.resolve_name("find_symbol") == "find_symbol"


def test_extra_roots_allows_access_outside_workspace(registry, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / "shared.txt").write_text("shared content")

    ctx = ToolContext(workspace_dir=workspace, extra_roots=(other_dir,))
    result = registry.execute("read_file", {"path": str(other_dir / "shared.txt")}, ctx, "c1")
    assert "shared content" in result.content
    assert not result.is_error


def test_without_extra_roots_still_sandboxed(registry, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / "secret.txt").write_text("nope")

    ctx = ToolContext(workspace_dir=workspace)
    result = registry.execute("read_file", {"path": str(other_dir / "secret.txt")}, ctx, "c1")
    assert result.is_error
    assert "Sandbox escape" in result.content
