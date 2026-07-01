"""Ollama provider -- local, first-class, native tool calling.

Talks to Ollama's own /api/chat endpoint (not the OpenAI-compatibility
shim) via httpx, since /api/chat gives structured `message.tool_calls`
and per-response `eval_count` usage without SSE `data:` framing.

Honors the OLLAMA_HOST environment variable -- geocentric/server.py
hardcodes http://127.0.0.1:11434 in several places and ignores this env
var; this provider does not repeat that bug.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, AsyncIterator, Optional

import httpx

from ..types import Message, ProviderCapabilities, StreamEvent, ToolCall, ToolDef
from .base import ModelProvider, ProviderError


def _default_base_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        return "http://127.0.0.1:11434"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _message_to_wire(msg: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        wire["tool_calls"] = [
            {"function": {"name": call.name, "arguments": call.arguments}} for call in msg.tool_calls
        ]
    if msg.role == "tool" and msg.name:
        wire["name"] = msg.name
    return wire


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, base_url: Optional[str] = None, timeout: float = 120.0):
        self.base_url = base_url or _default_base_url()
        self.timeout = timeout
        self._tool_unsupported_models: set[str] = set()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=True)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"Could not reach Ollama at {self.base_url}: {exc}") from exc
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Optional[list[ToolDef]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        use_tools = bool(tools) and model not in self._tool_unsupported_models
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_message_to_wire(m) for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if use_tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status_code == 400 and use_tools:
                        # Some models reject the "tools" field outright -- remember
                        # that and retry once without it so the turn still succeeds.
                        self._tool_unsupported_models.add(model)
                        async for event in self.stream_chat(
                            messages, model=model, tools=None, max_tokens=max_tokens, temperature=temperature
                        ):
                            yield event
                        return
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        message = chunk.get("message") or {}
                        content = message.get("content") or ""
                        if content:
                            yield StreamEvent(kind="text_delta", text=content)

                        for tool_call in message.get("tool_calls") or []:
                            func = tool_call.get("function", {})
                            raw_args = func.get("arguments", {})
                            if isinstance(raw_args, str):
                                try:
                                    raw_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    raw_args = {}
                            yield StreamEvent(
                                kind="tool_call",
                                tool_call=ToolCall(id=uuid.uuid4().hex, name=func.get("name", ""), arguments=raw_args),
                            )

                        if chunk.get("done"):
                            if "eval_count" in chunk:
                                usage = {
                                    "prompt_tokens": chunk.get("prompt_eval_count", 0),
                                    "completion_tokens": chunk.get("eval_count", 0),
                                }
                                yield StreamEvent(kind="usage", usage=usage)
                            yield StreamEvent(kind="done", finish_reason=chunk.get("done_reason", "stop"))
            except httpx.HTTPError as exc:
                yield StreamEvent(kind="error", text=f"Ollama request failed: {exc}")
                yield StreamEvent(kind="done", finish_reason="error")
