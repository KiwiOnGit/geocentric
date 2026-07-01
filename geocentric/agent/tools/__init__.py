"""Shared tool registry.

A tool is declared exactly once as a ToolSpec (name, JSON schema, handler).
Both the native tool-calling path (providers hand the model a JSON-schema
tool list and get back structured calls) and the fallback text-parsing path
(fallback_parser.py, for providers without native tool calling) dispatch
through the *same* ToolRegistry -- neither path duplicates tool logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..types import ToolDef, ToolResult


@dataclass
class ToolContext:
    """Per-invocation state passed to every handler.

    Deliberately NOT held as instance state on the registry itself, since a
    single registry/process may need to serve multiple workspaces (e.g. a
    future server-side reuse of this package) without cross-talk.
    """

    workspace_dir: Path
    on_status: Optional[Callable[[str], None]] = None
    # Additional directories granted via /add-dir. Filesystem tools may
    # resolve paths into these roots in addition to workspace_dir; empty by
    # default so single-workspace callers get today's exact sandboxing.
    extra_roots: tuple[Path, ...] = ()


ToolHandler = Callable[[dict[str, Any], ToolContext], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    requires_approval: bool = False
    # Old-style tags this tool should also be recognized as when parsing
    # fallback/tag-based model output (e.g. legacy "<write_file>" tags that
    # the from-scratch trained model was fine-tuned on).
    legacy_tag_aliases: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._legacy_alias_map: dict[str, str] = {}

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec
        for alias in spec.legacy_tag_aliases:
            self._legacy_alias_map[alias] = spec.name

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def resolve_name(self, name_or_alias: str) -> Optional[str]:
        if name_or_alias in self._specs:
            return name_or_alias
        return self._legacy_alias_map.get(name_or_alias)

    def all_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def to_native_tooldefs(self) -> list[ToolDef]:
        return [
            ToolDef(name=spec.name, description=spec.description, parameters=spec.parameters)
            for spec in self._specs.values()
        ]

    def to_prompt_catalog(self) -> str:
        """Human-readable tool catalog injected into fallback-provider prompts."""
        lines = []
        for spec in self._specs.values():
            props = spec.parameters.get("properties", {})
            arg_hint = ", ".join(props.keys())
            lines.append(f"- {spec.name}({arg_hint}): {spec.description}")
        return "\n".join(lines)

    def execute(self, name: str, arguments: dict[str, Any], ctx: ToolContext, call_id: str) -> ToolResult:
        resolved = self.resolve_name(name)
        spec = self._specs.get(resolved) if resolved else None
        if spec is None:
            return ToolResult(call_id=call_id, name=name, content=f"[TOOL ERROR] Unknown tool '{name}'.", is_error=True)
        try:
            content = spec.handler(arguments, ctx)
            return ToolResult(call_id=call_id, name=spec.name, content=content)
        except Exception as exc:
            return ToolResult(call_id=call_id, name=spec.name, content=f"[{spec.name.upper()} ERROR] {exc}", is_error=True)


def default_registry() -> ToolRegistry:
    """Registry for the CLI coding-agent surface (fs/search/shell/git/web/indexing)."""
    from . import fs as fs_tools
    from . import git as git_tools
    from . import indexing as indexing_tools
    from . import search as search_tools
    from . import shell as shell_tools
    from . import web as web_tools

    registry = ToolRegistry()
    for module in (fs_tools, search_tools, shell_tools, git_tools, web_tools, indexing_tools):
        for spec in module.SPECS:
            registry.register(spec)
    return registry
