"""OpenRouter provider.

OpenRouter is wire-compatible with OpenAI's Chat Completions `tools` schema,
so this is a ~15-line override of OpenAIProvider (base_url + headers + key
name) rather than a new implementation -- the concrete proof-point that
adding a provider to this system is small.
"""

from __future__ import annotations

from .openai_provider import OpenAIProvider

_FALLBACK_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "openai/gpt-4o",
    "qwen/qwen-2.5-coder-32b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
]


class OpenRouterProvider(OpenAIProvider):
    name = "openrouter"
    key_name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    extra_headers = {
        "HTTP-Referer": "https://github.com/KiwiOnGit/geocentric",
        "X-Title": "Geocentric Code",
    }
    fallback_models = _FALLBACK_MODELS
