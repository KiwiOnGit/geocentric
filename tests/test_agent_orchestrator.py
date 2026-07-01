"""Turn-loop tests using a scripted fake provider -- no network/Ollama required."""

from pathlib import Path

import pytest

from geocentric.agent.config import TurnLoopConfig
from geocentric.agent.orchestrator import run_turn_loop
from geocentric.agent.providers.base import ModelProvider
from geocentric.agent.tools import ToolContext, default_registry
from geocentric.agent.types import Message, ProviderCapabilities, StreamEvent, ToolCall


class ScriptedProvider(ModelProvider):
    """Replays one scripted list[StreamEvent] per call to stream_chat, in order."""

    name = "scripted"

    def __init__(self, turns: list[list[StreamEvent]], native: bool = True):
        self.turns = list(turns)
        self._native = native
        self.calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=self._native)

    async def list_models(self) -> list[str]:
        return ["scripted-model"]

    async def stream_chat(self, messages, *, model, tools, max_tokens, temperature):
        events = self.turns[self.calls] if self.calls < len(self.turns) else []
        self.calls += 1
        for event in events:
            yield event


async def _collect(provider, messages, cfg, registry=None, ctx=None):
    registry = registry or default_registry()
    ctx = ctx or ToolContext(workspace_dir=Path("/tmp"))
    events = []
    async for event in run_turn_loop(provider, "scripted-model", messages, registry, ctx, cfg):
        events.append(event)
    return events


async def test_single_tool_call_then_final_answer(tmp_path):
    provider = ScriptedProvider(
        [
            [StreamEvent(kind="tool_call", tool_call=ToolCall(id="1", name="read_file", arguments={"path": "x.txt"}))],
            [StreamEvent(kind="text_delta", text="Done reading.")],
        ]
    )
    (tmp_path / "x.txt").write_text("hello")
    ctx = ToolContext(workspace_dir=tmp_path)
    cfg = TurnLoopConfig(turn_limit=5, workspace_tools_required=True)
    messages = [Message(role="user", content="read x.txt")]

    events = await _collect(provider, messages, cfg, ctx=ctx)

    kinds = [e.kind for e in events]
    assert "tool_call" in kinds
    assert kinds[-1] == "done"
    assert events[-1].finish_reason == "stop"
    # Tool result was fed back into the conversation for the next turn.
    tool_messages = [m for m in messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "hello" in tool_messages[0].content


async def test_two_consecutive_toolless_turns_gives_up_gracefully():
    provider = ScriptedProvider(
        [
            [StreamEvent(kind="text_delta", text="thinking out loud")],
            [StreamEvent(kind="text_delta", text="still no tool call")],
        ]
    )
    cfg = TurnLoopConfig(turn_limit=5, workspace_tools_required=True)
    messages = [Message(role="user", content="do something")]

    events = await _collect(provider, messages, cfg)

    assert provider.calls == 2  # gave up after exactly 2 toolless turns, not turn_limit
    assert events[-1].kind == "done"
    assert events[-1].finish_reason == "stop"


async def test_workspace_tools_not_required_accepts_first_toolless_turn():
    provider = ScriptedProvider([[StreamEvent(kind="text_delta", text="just chatting")]])
    cfg = TurnLoopConfig(turn_limit=5, workspace_tools_required=False)
    messages = [Message(role="user", content="hi")]

    events = await _collect(provider, messages, cfg)

    assert provider.calls == 1
    assert events[-1].finish_reason == "stop"


async def test_turn_limit_is_enforced():
    always_calls_tool = [
        [StreamEvent(kind="tool_call", tool_call=ToolCall(id=str(i), name="git_status", arguments={}))] for i in range(10)
    ]
    provider = ScriptedProvider(always_calls_tool)
    cfg = TurnLoopConfig(turn_limit=3, workspace_tools_required=True)
    messages = [Message(role="user", content="loop forever")]

    events = await _collect(provider, messages, cfg)

    assert provider.calls == 3
    assert events[-1].finish_reason == "turn_limit"


async def test_approval_denial_skips_execution_without_crashing(tmp_path):
    provider = ScriptedProvider(
        [
            [StreamEvent(kind="tool_call", tool_call=ToolCall(id="1", name="write_file", arguments={"path": "x.txt", "content": "y"}))],
            [StreamEvent(kind="text_delta", text="ok, skipped")],
        ]
    )

    async def deny(_call):
        return False

    cfg = TurnLoopConfig(turn_limit=5, workspace_tools_required=True, approve=deny)
    ctx = ToolContext(workspace_dir=tmp_path)
    messages = [Message(role="user", content="write a file")]

    await _collect(provider, messages, cfg, ctx=ctx)

    assert not (tmp_path / "x.txt").exists()
    tool_messages = [m for m in messages if m.role == "tool"]
    assert tool_messages[0].content == "[USER DENIED THIS ACTION]"


async def test_provider_error_terminates_loop_immediately():
    provider = ScriptedProvider([[StreamEvent(kind="error", text="network exploded")]])
    cfg = TurnLoopConfig(turn_limit=5)
    messages = [Message(role="user", content="hi")]

    events = await _collect(provider, messages, cfg)

    assert provider.calls == 1
    assert events[-1].kind == "done"
    assert events[-1].finish_reason == "error"


async def test_fallback_provider_parses_json_fence_tool_calls(tmp_path):
    provider = ScriptedProvider(
        [
            [StreamEvent(kind="text_delta", text='```tool_call\n{"name": "read_file", "arguments": {"path": "x.txt"}}\n```')],
            [StreamEvent(kind="text_delta", text="Got it.")],
        ],
        native=False,
    )
    (tmp_path / "x.txt").write_text("content!")
    ctx = ToolContext(workspace_dir=tmp_path)
    cfg = TurnLoopConfig(turn_limit=5, workspace_tools_required=True)
    messages = [Message(role="user", content="read the file")]

    events = await _collect(provider, messages, cfg, ctx=ctx)

    assert any(e.kind == "tool_call" and e.tool_call.name == "read_file" for e in events)
    assert events[-1].finish_reason == "stop"
