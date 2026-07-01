"""Anthropic provider -- native tool calling via the official SDK."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from ..keys import default_store
from ..types import Message, ProviderCapabilities, StreamEvent, ToolCall, ToolDef
from .base import ModelProvider, ProviderError

_FALLBACK_MODELS = [
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-haiku-4-5-20251001",
]


def _to_anthropic_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            anthropic_messages.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

    for msg in messages:
        if msg.role == "system":
            if msg.content:
                system_parts.append(msg.content)
            continue
        if msg.role == "tool":
            pending_tool_results.append(
                {"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}
            )
            continue
        flush_tool_results()
        if msg.role == "assistant":
            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for call in msg.tool_calls:
                content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            anthropic_messages.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
        else:
            anthropic_messages.append({"role": "user", "content": msg.content})
    flush_tool_results()
    return "\n\n".join(system_parts), anthropic_messages


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def _resolve_api_key(self) -> Optional[str]:
        return self._api_key or default_store().get("anthropic")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=True)

    async def list_models(self) -> list[str]:
        import anthropic

        api_key = self._resolve_api_key()
        if not api_key:
            return list(_FALLBACK_MODELS)
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            page = await client.models.list(limit=50)
            names = [m.id for m in page.data]
            return names or list(_FALLBACK_MODELS)
        except Exception:
            return list(_FALLBACK_MODELS)

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Optional[list[ToolDef]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        import anthropic

        api_key = self._resolve_api_key()
        if not api_key:
            yield StreamEvent(kind="error", text="No Anthropic API key configured. Use /apikey anthropic to set one.")
            yield StreamEvent(kind="done", finish_reason="error")
            return

        client = anthropic.AsyncAnthropic(api_key=api_key)
        system, anthropic_messages = _to_anthropic_messages(messages)
        kwargs: dict[str, Any] = dict(
            model=model, max_tokens=max_tokens, temperature=temperature, messages=anthropic_messages
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]

        block_types: dict[int, str] = {}
        tool_meta: dict[int, tuple[str, str]] = {}
        partial_json: dict[int, str] = {}

        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    etype = event.type
                    if etype == "content_block_start":
                        block = event.content_block
                        block_types[event.index] = block.type
                        if block.type == "tool_use":
                            tool_meta[event.index] = (block.id, block.name)
                            partial_json[event.index] = ""
                    elif etype == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(kind="text_delta", text=delta.text)
                        elif delta.type == "input_json_delta":
                            partial_json[event.index] = partial_json.get(event.index, "") + delta.partial_json
                    elif etype == "content_block_stop":
                        if block_types.get(event.index) == "tool_use":
                            call_id, call_name = tool_meta.get(event.index, ("", ""))
                            raw = partial_json.get(event.index) or "{}"
                            try:
                                args = json.loads(raw)
                            except json.JSONDecodeError:
                                args = {}
                            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id=call_id, name=call_name, arguments=args))
                    elif etype == "message_delta":
                        usage = getattr(event, "usage", None)
                        if usage is not None:
                            yield StreamEvent(kind="usage", usage={"completion_tokens": usage.output_tokens})

                final = await stream.get_final_message()
                yield StreamEvent(kind="done", finish_reason=final.stop_reason)
        except Exception as exc:
            yield StreamEvent(kind="error", text=f"Anthropic request failed: {exc}")
            yield StreamEvent(kind="done", finish_reason="error")
