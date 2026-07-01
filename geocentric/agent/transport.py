"""Transport abstraction used by the CLI.

LocalCoreTransport runs the full agent loop in-process (no server, no HTTP
hop) -- the new default. RemoteHttpTransport preserves today's `/connect`
and `--server` behavior exactly: the CLI sends the whole conversation to a
running `geocentric serve` instance and streams back its reply over the
existing SSE wire format (geocentric/server.py's `sse_chunk`), completely
untouched by this change. Both expose the same `run_turn()` shape so
interactive_cli.py never has to branch on which transport is active.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

from .config import AgentConfig, TurnLoopConfig
from .orchestrator import run_turn_loop
from .prompt_builder import SystemPromptBuilder
from .providers import get_provider
from .providers.base import ModelProvider
from .tools import ToolContext, ToolRegistry, default_registry
from .types import Message, StreamEvent, ToolCall


class TransportClient(ABC):
    @abstractmethod
    def run_turn(self, messages: list[Message], config: AgentConfig) -> AsyncIterator[StreamEvent]: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...


class LocalCoreTransport(TransportClient):
    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        registry: Optional[ToolRegistry] = None,
        approve: Optional[Callable[[ToolCall], Awaitable[bool]]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        provider_kwargs: Optional[dict[str, dict[str, Any]]] = None,
    ):
        self.workspace_dir = workspace_dir or Path.cwd()
        self.registry = registry or default_registry()
        self.approve = approve
        self.on_status = on_status
        self.provider_kwargs = provider_kwargs or {}
        self._provider_cache: dict[str, ModelProvider] = {}

    def _provider(self, name: str) -> ModelProvider:
        if name not in self._provider_cache:
            self._provider_cache[name] = get_provider(name, **self.provider_kwargs.get(name, {}))
        return self._provider_cache[name]

    async def run_turn(self, messages: list[Message], config: AgentConfig) -> AsyncIterator[StreamEvent]:
        provider = self._provider(config.provider)
        native = provider.capabilities().native_tool_calling

        if not messages or messages[0].role != "system":
            builder = SystemPromptBuilder(self.workspace_dir)
            system_text = builder.build(effort=config.effort, native_tool_calling=native, registry=self.registry)
            messages.insert(0, Message(role="system", content=system_text))

        ctx = ToolContext(workspace_dir=self.workspace_dir, on_status=self.on_status)
        cfg = TurnLoopConfig(
            turn_limit=config.resolved_turn_limit(),
            max_tokens_per_turn=config.max_tokens_per_turn,
            temperature=config.temperature,
            workspace_tools_required=config.agent_mode,
            approve=self.approve,
            on_status=self.on_status,
        )
        model = config.model or (await provider.list_models() or [""])[0]
        async for event in run_turn_loop(provider, model, messages, self.registry, ctx, cfg):
            yield event

    async def ping(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return await self._provider("ollama").list_models()


def _extract_delta(packet: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(packet, dict):
        return str(packet or ""), ""
    choices = packet.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}
        return str(delta.get("content") or ""), str(delta.get("reasoning_content") or "")
    return (
        str(packet.get("reply") or packet.get("content") or packet.get("text") or ""),
        str(packet.get("reasoning_content") or packet.get("thinking") or ""),
    )


class RemoteHttpTransport(TransportClient):
    """Talks to an existing `geocentric serve` instance exactly as today's
    interactive_cli.py does -- same /api/chat payload shape, same SSE
    framing. The remote server drives its own tool-execution loop
    internally; from here it looks like a single streamed reply."""

    def __init__(self, server: str, token: str = "", model: str = "", model_mode: str = "thinking"):
        self.server = server.rstrip("/")
        self.token = token
        self.model = model
        self.model_mode = model_mode

    def _url(self, path: str) -> str:
        return f"{self.server}{path if path.startswith('/') else '/' + path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "X-Geocentric-Client": "cli"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def ping(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for path in ("/api/status", "/api/v1/models"):
                try:
                    resp = await client.get(self._url(path), headers=self._headers())
                    if resp.status_code < 500:
                        return True
                except httpx.HTTPError:
                    continue
        return False

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(self._url("/api/v1/models"), headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    async def run_turn(self, messages: list[Message], config: AgentConfig) -> AsyncIterator[StreamEvent]:
        from geocentric.cli_system_prompt import load_system_prompt

        payload = {
            "model": self.model or config.model,
            "mode": self.model_mode,
            "modelMode": self.model_mode,
            "searchWeb": config.search_web,
            "conversationId": "",
            "agentMode": config.agent_mode,
            "projectPath": os.getcwd(),
            "systemPrompt": load_system_prompt(),
            "stream": True,
            "effort": config.effort,
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "tool"],
        }

        final_text = ""
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream("POST", self._url("/api/chat"), json=payload, headers=self._headers()) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        content, reasoning = _extract_delta(parsed)
                        if content:
                            final_text += content
                            yield StreamEvent(kind="text_delta", text=content)
                        if reasoning:
                            yield StreamEvent(kind="reasoning_delta", text=reasoning)
                        if parsed.get("usage"):
                            yield StreamEvent(kind="usage", usage=parsed["usage"])
        except httpx.HTTPError as exc:
            yield StreamEvent(kind="error", text=f"Remote request failed: {exc}")
            yield StreamEvent(kind="done", finish_reason="error")
            return

        messages.append(Message(role="assistant", content=final_text))
        yield StreamEvent(kind="done", finish_reason="stop")
