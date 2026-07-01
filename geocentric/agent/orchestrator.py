"""The single, provider-agnostic multi-turn agent loop.

Replaces the duplicated turn-loop logic that existed three times in
geocentric/server.py (event_stream_ollama in web_chat, the near-identical
copy in /v1/chat/completions, and the local-model event_stream) -- written
once here, driven purely by StreamEvents so it never needs to know whether a
tool call was native or scraped from text.
"""

from __future__ import annotations

from typing import AsyncIterator

from .config import TurnLoopConfig
from .execution import run_tool
from .fallback_parser import extract_tool_calls
from .providers.base import ModelProvider
from .tools import ToolContext, ToolRegistry
from .types import Message, StreamEvent, ToolCall

TOOLLESS_FEEDBACK = (
    "You did not call any tools this turn, but the task appears to still require workspace "
    "actions to complete. If you are truly finished, say so explicitly; otherwise call the "
    "appropriate tool now."
)


async def run_turn_loop(
    provider: ModelProvider,
    model: str,
    messages: list[Message],
    registry: ToolRegistry,
    ctx: ToolContext,
    cfg: TurnLoopConfig,
) -> AsyncIterator[StreamEvent]:
    """Mutates `messages` in place, appending each assistant/tool turn, so the
    caller's own message history ends up holding the full transcript."""
    native = provider.capabilities().native_tool_calling
    tool_defs = registry.to_native_tooldefs() if native else None
    consecutive_toolless_turns = 0

    for turn_index in range(cfg.turn_limit):
        has_more_turns = turn_index + 1 < cfg.turn_limit
        accumulated_text = ""
        tool_calls: list[ToolCall] = []
        saw_error = False

        async for event in provider.stream_chat(
            messages,
            model=model,
            tools=tool_defs,
            max_tokens=cfg.max_tokens_per_turn,
            temperature=cfg.temperature,
        ):
            if event.kind == "text_delta":
                accumulated_text += event.text
                yield event
            elif event.kind == "tool_call" and event.tool_call:
                tool_calls.append(event.tool_call)
            elif event.kind == "error":
                saw_error = True
                yield event
            elif event.kind in ("reasoning_delta", "usage"):
                yield event
            # provider-level "done" events are internal to this turn; the
            # loop emits its own "done" exactly once, at the very end.

        if saw_error:
            yield StreamEvent(kind="done", finish_reason="error")
            return

        if not native:
            tool_calls = extract_tool_calls(accumulated_text, registry)

        messages.append(Message(role="assistant", content=accumulated_text, tool_calls=tool_calls))

        if not tool_calls:
            if cfg.workspace_tools_required and has_more_turns:
                consecutive_toolless_turns += 1
                if consecutive_toolless_turns >= 2:
                    yield StreamEvent(kind="done", finish_reason="stop")
                    return
                messages.append(Message(role="user", content=TOOLLESS_FEEDBACK))
                if cfg.on_status:
                    cfg.on_status("Waiting for a tool call or explicit completion...")
                continue
            yield StreamEvent(kind="done", finish_reason="stop")
            return

        consecutive_toolless_turns = 0
        for call in tool_calls:
            resolved_name = registry.resolve_name(call.name) or call.name
            spec = registry.get(resolved_name)
            if spec and spec.requires_approval and cfg.approve is not None:
                approved = await cfg.approve(call)
                if not approved:
                    messages.append(
                        Message(role="tool", tool_call_id=call.id, name=call.name, content="[USER DENIED THIS ACTION]")
                    )
                    continue
            yield StreamEvent(kind="tool_call", tool_call=call)
            result = await run_tool(call, registry, ctx)
            yield StreamEvent(kind="status", tool_result=result, text=result.content)
            messages.append(Message(role="tool", tool_call_id=result.call_id, name=result.name, content=result.content))

    yield StreamEvent(kind="done", finish_reason="turn_limit")
