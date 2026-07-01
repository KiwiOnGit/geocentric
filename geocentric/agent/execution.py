"""Runs a single tool call against the shared registry off the event loop."""

from __future__ import annotations

import asyncio

from .tools import ToolContext, ToolRegistry
from .types import ToolCall, ToolResult


async def run_tool(call: ToolCall, registry: ToolRegistry, ctx: ToolContext) -> ToolResult:
    return await asyncio.to_thread(registry.execute, call.name, call.arguments, ctx, call.id)
