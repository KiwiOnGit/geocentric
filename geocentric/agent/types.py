"""Provider-neutral data types shared by every model provider and the orchestrator.

Every ModelProvider implementation (native tool-calling or fallback/tag-based)
speaks these types. The orchestrator never has to know which provider produced
a ToolCall or whether it came from a structured API field or was scraped out
of streamed text -- that distinction is fully absorbed inside each provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ProviderCapabilities:
    native_tool_calling: bool
    supports_streaming: bool = True
    supports_system_role: bool = True
    max_context_tokens: Optional[int] = None


EventKind = Literal[
    "text_delta",
    "reasoning_delta",
    "tool_call",
    "usage",
    "status",
    "error",
    "done",
]


@dataclass
class StreamEvent:
    kind: EventKind
    text: str = ""
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
    usage: Optional[dict[str, int]] = None
    finish_reason: Optional[str] = None
