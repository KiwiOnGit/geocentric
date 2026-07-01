"""Runtime configuration for a single agent turn-loop invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_AGENT_TURN_LIMIT = 15
DEFAULT_CHAT_TURN_LIMIT = 8

PROVIDER_NAMES = ("ollama", "local", "anthropic", "openai", "openrouter", "gemini")

# Providers that speak native function/tool calling. Everything else falls
# back to the JSON-fenced / legacy-XML text parser in fallback_parser.py.
NATIVE_TOOL_CALLING_PROVIDERS = frozenset({"ollama", "anthropic", "openai", "openrouter", "gemini"})


@dataclass
class AgentConfig:
    provider: str = "ollama"
    model: str = ""
    effort: str = "medium"
    agent_mode: bool = True
    search_web: bool = False
    max_tokens_per_turn: int = 4096
    temperature: float = 0.7
    turn_limit: Optional[int] = None

    def resolved_turn_limit(self) -> int:
        if self.turn_limit is not None:
            return self.turn_limit
        return DEFAULT_AGENT_TURN_LIMIT if self.agent_mode else DEFAULT_CHAT_TURN_LIMIT


@dataclass
class TurnLoopConfig:
    turn_limit: int
    max_tokens_per_turn: int = 4096
    temperature: float = 0.7
    workspace_tools_required: bool = True
    approve: Optional[Callable] = None
    on_status: Optional[Callable[[str], None]] = None
