"""Local provider: wraps the existing from-scratch/HF checkpoint stack.

Zero changes to geocentric/checkpoint.py or geocentric/generate.py -- this
module only adapts their already-generic signatures to the ModelProvider
interface. No native tool calling (the trained model was never taught a
function-calling protocol), so the orchestrator drives this provider through
the fallback text-parser instead.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncIterator, Optional

from ..types import Message, ProviderCapabilities, StreamEvent, ToolDef
from .base import ModelProvider, ProviderError


class LocalTorchProvider(ModelProvider):
    name = "local"

    def __init__(self, model_dir: str, dtype_name: str = "auto", modelver: str = "Geocentric 2.1"):
        self.model_dir = model_dir
        self.dtype_name = dtype_name
        self.modelver = modelver
        self._cache: Optional[tuple[Any, Any, Any]] = None  # (model, tokenizer, device)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(native_tool_calling=False)

    async def list_models(self) -> list[str]:
        return [self.model_dir]

    def _load_sync(self) -> tuple[Any, Any, Any]:
        if self._cache is not None:
            return self._cache
        from geocentric.checkpoint import load_model_and_tokenizer
        from geocentric.device import resolve_dtype, select_device

        device = select_device()
        dtype = resolve_dtype(device, self.dtype_name)
        try:
            model, tokenizer = load_model_and_tokenizer(self.model_dir, device, dtype, self.modelver)
        except Exception as exc:
            raise ProviderError(f"Failed to load local model from '{self.model_dir}': {exc}") from exc
        model.eval()
        self._cache = (model, tokenizer, device)
        return self._cache

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Optional[list[ToolDef]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        from geocentric.generate import build_chat_prompt, stream_text

        try:
            model_obj, tokenizer, device = await asyncio.to_thread(self._load_sync)
        except ProviderError as exc:
            yield StreamEvent(kind="error", text=str(exc))
            yield StreamEvent(kind="done", finish_reason="error")
            return

        prompt = build_chat_prompt([{"role": m.role, "content": m.content} for m in messages])

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL_DONE = object()

        def _worker() -> None:
            try:
                for token in stream_text(
                    model_obj,
                    tokenizer,
                    prompt,
                    device,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
            except Exception as exc:  # generation failures shouldn't crash the turn loop
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", SENTINEL_DONE))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        while True:
            kind, payload = await queue.get()
            if kind == "token":
                yield StreamEvent(kind="text_delta", text=payload)
            elif kind == "error":
                yield StreamEvent(kind="error", text=f"Local generation error: {payload}")
                break
            else:
                break
        yield StreamEvent(kind="done", finish_reason="stop")
