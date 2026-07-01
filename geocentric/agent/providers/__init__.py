"""Provider registry: name -> ModelProvider factory.

Adding a new provider is: write one class implementing ModelProvider, then
add one line here. The orchestrator and CLI never branch on provider name.
"""

from __future__ import annotations

from typing import Optional

from .base import ModelProvider

_FACTORIES = {}


def _build_registry():
    from . import anthropic_provider, gemini_provider, local_provider, ollama, openai_provider, openrouter_provider

    return {
        "ollama": lambda **kw: ollama.OllamaProvider(**kw),
        "anthropic": lambda **kw: anthropic_provider.AnthropicProvider(**kw),
        "openai": lambda **kw: openai_provider.OpenAIProvider(**kw),
        "openrouter": lambda **kw: openrouter_provider.OpenRouterProvider(**kw),
        "gemini": lambda **kw: gemini_provider.GeminiProvider(**kw),
        "local": lambda **kw: local_provider.LocalTorchProvider(**kw),
    }


def get_provider(name: str, **kwargs) -> ModelProvider:
    global _FACTORIES
    if not _FACTORIES:
        _FACTORIES = _build_registry()
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"Unknown provider '{name}'. Available: {', '.join(sorted(_FACTORIES))}")
    return factory(**kwargs)


def provider_names() -> list[str]:
    if not _FACTORIES:
        return ["ollama", "anthropic", "openai", "openrouter", "gemini", "local"]
    return sorted(_FACTORIES)
