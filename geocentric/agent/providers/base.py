"""ModelProvider interface.

Every provider (native tool-calling or fallback/tag-based) implements this
same interface. The orchestrator only ever consumes StreamEvents from
stream_chat() -- it never knows whether a tool call was parsed from a
structured API field or scraped out of streamed text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from ..types import Message, ProviderCapabilities, StreamEvent, ToolDef


class ModelProvider(ABC):
    name: str = "base"

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    @abstractmethod
    def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Optional[list[ToolDef]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[StreamEvent]:
        """Always an async generator, even when the underlying SDK is sync-only
        (wrap sync calls with asyncio.to_thread + a queue)."""
        ...


class ProviderError(RuntimeError):
    pass
