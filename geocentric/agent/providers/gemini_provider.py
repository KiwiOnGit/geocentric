"""Google Gemini provider -- native tool calling via the google-genai SDK.

Gemini's function-calling schema differs from OpenAI/Anthropic in a few
fiddly ways (role names "user"/"model" instead of "user"/"assistant", tool
results sent back as `function_response` parts rather than a "tool" role)
-- all absorbed here so the orchestrator stays provider-neutral.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from ..keys import default_store
from ..types import Message, ProviderCapabilities, StreamEvent, ToolCall, ToolDef
from .base import ModelProvider

_FALLBACK_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]


class GeminiProvider(ModelProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def _resolve_api_key(self) -> Optional[str]:
        return self._api_key or default_store().get("gemini")

    def _client(self):
        from google import genai

        return genai.Client(api_key=self._resolve_api_key())

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=True)

    async def list_models(self) -> list[str]:
        if not self._resolve_api_key():
            return list(_FALLBACK_MODELS)
        try:
            client = self._client()
            models = await client.aio.models.list()
            names = [m.name.replace("models/", "") for m in models]
            return names or list(_FALLBACK_MODELS)
        except Exception:
            return list(_FALLBACK_MODELS)

    def _to_contents(self, messages: list[Message]) -> tuple[str, list[Any]]:
        from google.genai import types

        system_parts: list[str] = []
        contents: list[Any] = []
        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                continue
            if msg.role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(name=msg.name or "", response={"result": msg.content})],
                    )
                )
                continue
            if msg.role == "assistant":
                parts = []
                if msg.content:
                    parts.append(types.Part(text=msg.content))
                for call in msg.tool_calls:
                    parts.append(types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments)))
                contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
            else:
                contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        return "\n\n".join(system_parts), contents

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
            yield StreamEvent(kind="error", text="No Gemini API key configured. Use /apikey gemini to set one.")
            yield StreamEvent(kind="done", finish_reason="error")
            return

        from google.genai import types

        system_text, contents = self._to_contents(messages)
        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_text:
            config_kwargs["system_instruction"] = system_text
        if tools:
            config_kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.parameters)
                        for t in tools
                    ]
                )
            ]
        config = types.GenerateContentConfig(**config_kwargs)

        try:
            client = self._client()
            stream = await client.aio.models.generate_content_stream(model=model, contents=contents, config=config)
            finish_reason = "stop"
            async for chunk in stream:
                for candidate in getattr(chunk, "candidates", None) or []:
                    if candidate.finish_reason:
                        finish_reason = str(candidate.finish_reason)
                    content = getattr(candidate, "content", None)
                    if not content or not content.parts:
                        continue
                    for part in content.parts:
                        if getattr(part, "text", None):
                            yield StreamEvent(kind="text_delta", text=part.text)
                        function_call = getattr(part, "function_call", None)
                        if function_call:
                            yield StreamEvent(
                                kind="tool_call",
                                tool_call=ToolCall(
                                    id=f"gemini-{function_call.name}-{id(function_call)}",
                                    name=function_call.name,
                                    arguments=dict(function_call.args or {}),
                                ),
                            )
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    yield StreamEvent(
                        kind="usage",
                        usage={
                            "prompt_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                            "completion_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                        },
                    )
            yield StreamEvent(kind="done", finish_reason=finish_reason)
        except Exception as exc:
            yield StreamEvent(kind="error", text=f"Gemini request failed: {exc}")
            yield StreamEvent(kind="done", finish_reason="error")
