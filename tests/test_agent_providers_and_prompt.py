from pathlib import Path

import pytest

from geocentric.agent.prompt_builder import SystemPromptBuilder
from geocentric.agent.providers import get_provider, provider_names
from geocentric.agent.tools import default_registry


def test_all_declared_providers_are_registered():
    names = provider_names()
    assert set(names) == {"ollama", "anthropic", "openai", "openrouter", "gemini", "local"}


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_provider("not-a-real-provider")


def test_cloud_providers_report_native_tool_calling():
    for name in ("ollama", "anthropic", "openai", "openrouter", "gemini"):
        provider = get_provider(name)
        assert provider.capabilities().native_tool_calling is True


def test_local_provider_has_no_native_tool_calling():
    provider = get_provider("local", model_dir="/nonexistent")
    assert provider.capabilities().native_tool_calling is False


def test_openrouter_overrides_base_url_and_key_name():
    provider = get_provider("openrouter")
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.key_name == "openrouter"
    assert provider.name == "openrouter"


def test_prompt_builder_includes_project_context(tmp_path: Path):
    (tmp_path / "GEOCENTRIC.md").write_text("Always use type hints.")
    builder = SystemPromptBuilder(tmp_path)
    prompt = builder.build(effort="high", native_tool_calling=True)
    assert "Always use type hints." in prompt
    assert "[Project context]" in prompt


def test_native_prompt_has_no_tool_catalog(tmp_path: Path):
    builder = SystemPromptBuilder(tmp_path)
    prompt = builder.build(native_tool_calling=True, registry=default_registry())
    assert "Tool calling format" not in prompt


def test_fallback_prompt_includes_tool_catalog(tmp_path: Path):
    builder = SystemPromptBuilder(tmp_path)
    prompt = builder.build(native_tool_calling=False, registry=default_registry())
    assert "Tool calling format" in prompt
    assert "write_file(" in prompt


def test_custom_systemprompt_md_overrides_default(tmp_path: Path):
    (tmp_path / "SYSTEMPROMPT.md").write_text("Custom persona: be a pirate.")
    builder = SystemPromptBuilder(tmp_path)
    prompt = builder.build()
    assert "Custom persona: be a pirate." in prompt
    assert "Geocentric Code, a local-first AI coding agent" not in prompt
