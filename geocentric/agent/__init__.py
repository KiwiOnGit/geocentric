"""Geocentric agent core.

A provider-agnostic coding-agent engine: model providers (local + cloud),
a shared tool registry, and a single turn-loop orchestrator. Designed to be
imported directly by the CLI (no HTTP server required) and, in the future,
reusable by geocentric/server.py for the web/mac-app surfaces without any
change to this package.
"""

from __future__ import annotations

from .types import (
    Message,
    ProviderCapabilities,
    StreamEvent,
    ToolCall,
    ToolDef,
    ToolResult,
)
from .config import AgentConfig

__all__ = [
    "Message",
    "ProviderCapabilities",
    "StreamEvent",
    "ToolCall",
    "ToolDef",
    "ToolResult",
    "AgentConfig",
]
