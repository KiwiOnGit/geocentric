import importlib

import pytest

from geocentric.cli_dashboard import ClaudeCodeDashboard


@pytest.fixture
def runtime_module():
    return importlib.import_module("geocentric.server")


def test_extract_status_tags_and_tool_progress(runtime_module):
    text = '<status>Gathering context</status> <write_file filename="a.py">print(1)</write_file>'
    cleaned, statuses = runtime_module.extract_status_tags(text)
    assert cleaned == '<write_file filename="a.py">print(1)</write_file>'
    assert statuses == ["Gathering context"]
    assert runtime_module.extract_tool_progress_event(text) == "Writing file: a.py"


def test_workspace_tool_guard_blocks_unmapped_claims(runtime_module):
    claim = "I updated your index file"
    assert runtime_module.enforce_tool_claim_guard(claim, "") is False
    assert runtime_module.enforce_tool_claim_guard(claim, '<write_file filename="index.txt"></write_file>') is True


def test_stream_status_theme_mapping(runtime_module):
    assert runtime_module.classify_status_theme("blurpling context") == "gathering"
    assert runtime_module.classify_status_theme("pondering the result") == "thinking"
    assert runtime_module.classify_status_theme("deploying the agent") == "executing"


def test_dashboard_effort_and_tokens_update_live():
    dash = ClaudeCodeDashboard(model="demo", mode="thinking", server="http://127.0.0.1:8000", effort="medium")
    dash.set_effort("low")
    assert dash.effort == "low"
    dash.update_thinking(detail="Generating", reasoning_tokens=3, token_count=5)
    assert dash.reasoning_tokens == 3
    assert dash.token_count == 5
