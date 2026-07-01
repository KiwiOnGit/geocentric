"""OpenAI provider -- native tool calling via the official SDK.

Also the base class for OpenRouterProvider: OpenRouter is wire-compatible
with OpenAI's Chat Completions `tools` schema, so it only needs to override
the base_url/headers/key-lookup-name (see openrouter_provider.py).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Optional

from ..keys import default_store
from ..types import Message, ProviderCapabilities, StreamEvent, ToolCall, ToolDef
from .base import ModelProvider

_FALLBACK_MODELS = ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                        }
                        for call in msg.tool_calls
                    ],
                }
            )
        elif msg.role == "tool":
            out.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out


class OpenAIProvider(ModelProvider):
    name = "openai"
    key_name = "openai"
    base_url: Optional[str] = None
    extra_headers: dict[str, str] = {}
    fallback_models = _FALLBACK_MODELS

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def _resolve_api_key(self) -> Optional[str]:
        return self._api_key or default_store().get(self.key_name)

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._resolve_api_key() or "unset",
            base_url=self.base_url,
            default_headers=self.extra_headers or None,
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=True)

    async def list_models(self) -> list[str]:
        if not self._resolve_api_key():
            return list(self.fallback_models)
        try:
            page = await self._client().models.list()
            names = [m.id for m in page.data]
            return names or list(self.fallback_models)
        except Exception:
            return list(self.fallback_models)

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Optional[list[ToolDef]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        if not self._resolve_api_key():
            yield StreamEvent(
                kind="error",
                text=f"No {self.name} API key configured. Use /apikey {self.key_name} to set one.",
            )
            yield StreamEvent(kind="done", finish_reason="error")
            return

        kwargs: dict[str, Any] = dict(
            model=model,
            messages=_to_openai_messages(messages),
            stream=True,
            stream_options={"include_usage": True},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]

        tool_calls_acc: dict[int, dict[str, Any]] = {}
        try:
            stream = await self._client().chat.completions.create(**kwargs)
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    yield StreamEvent(
                        kind="usage",
                        usage={
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                        },
                    )
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    yield StreamEvent(kind="text_delta", text=delta.content)
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        entry = tool_calls_acc.setdefault(tc_delta.index, {"id": None, "name": "", "arguments": ""})
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                entry["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                entry["arguments"] += tc_delta.function.arguments
                if choice.finish_reason:
                    for _, entry in sorted(tool_calls_acc.items()):
                        try:
                            args = json.loads(entry["arguments"] or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamEvent(
                            kind="tool_call",
                            tool_call=ToolCall(id=entry["id"] or uuid.uuid4().hex, name=entry["name"], arguments=args),
                        )
                    tool_calls_acc = {}
                    yield StreamEvent(kind="done", finish_reason=choice.finish_reason)
        except Exception as exc:
            yield StreamEvent(kind="error", text=f"{self.name} request failed: {exc}")
            yield StreamEvent(kind="done", finish_reason="error")
