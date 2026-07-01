"""Tool-call extraction for providers without native function calling.

Two formats are recognized, in this order:

1. JSON-fenced blocks (new, preferred for any provider that can be steered
   via the system prompt):

       ```tool_call
       {"name": "write_file", "arguments": {"path": "x.py", "content": "..."}}
       ```

   This is immune to the classic failure mode of the old XML-tag regexes in
   geocentric/server.py's process_sandbox_tags: a `write_file` whose file
   content itself contains the literal substring "</write_file>" would
   truncate the match early. `json.loads` has no such problem.

2. Legacy XML tags (`<write_file filename="x">...</write_file>`, etc.) --
   kept because the project's own from-scratch-trained local model was
   almost certainly SFT'd on this vocabulary (see geocentric/data.py /
   train_sft.py) and cannot be retrained as part of this change. Only a
   pragmatic subset of the old tag shapes is supported here (one call per
   tag, attributes mapped to the new structured tool schema) -- the old
   per-tool insert/delete/replace-by-line-number edit micro-syntax is not
   byte-for-byte replicated; `edit_file` in legacy mode expects the same
   start_line/end_line/content shape as the native schema.
"""

from __future__ import annotations

import html
import json
import re
import uuid
from typing import Any, Callable, Optional

from .tools import ToolRegistry
from .types import ToolCall

_JSON_FENCE_RE = re.compile(r"```tool_call\s*\n([\s\S]*?)```", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

LegacyArgBuilder = Callable[[dict[str, str], str], dict[str, Any]]


def _default_builder(schema_properties: list[str]) -> LegacyArgBuilder:
    def build(attrs: dict[str, str], body: str) -> dict[str, Any]:
        if attrs:
            return dict(attrs)
        if schema_properties:
            return {schema_properties[0]: body.strip()}
        return {}

    return build


_LEGACY_ARG_BUILDERS: dict[str, LegacyArgBuilder] = {
    "write_file": lambda attrs, body: {"path": attrs.get("filename") or attrs.get("path", ""), "content": body},
    "read_file": lambda attrs, body: {"path": attrs.get("filename") or attrs.get("path") or body.strip()},
    "delete_file": lambda attrs, body: {"path": attrs.get("filename") or attrs.get("path") or body.strip()},
    "edit_file": lambda attrs, body: {
        "path": attrs.get("filename") or attrs.get("path", ""),
        "start_line": int(attrs.get("start_line", 1)),
        "end_line": int(attrs.get("end_line", attrs.get("start_line", 1))),
        "content": body,
    },
    "move_file": lambda attrs, body: {"source": attrs.get("from", ""), "destination": attrs.get("to", "")},
    "copy_file": lambda attrs, body: {"source": attrs.get("from", ""), "destination": attrs.get("to", "")},
    "make_directory": lambda attrs, body: {"path": attrs.get("path") or body.strip()},
    "list_directory": lambda attrs, body: {"path": attrs.get("path") or body.strip() or "."},
    "stat_path": lambda attrs, body: {"path": attrs.get("path") or body.strip()},
    "view_project_tree": lambda attrs, body: {},
    "grep": lambda attrs, body: {"pattern": attrs.get("pattern") or body.strip(), **({"glob": attrs["glob"]} if "glob" in attrs else {})},
    "run_command": lambda attrs, body: {"command": attrs.get("command") or body.strip()},
    "git_status": lambda attrs, body: {},
    "git_diff": lambda attrs, body: {"path": attrs.get("path", "")} if attrs.get("path") else {},
    "git_commit": lambda attrs, body: {"message": attrs.get("message") or body.strip()},
    "git_branch": lambda attrs, body: {},
    "web_search": lambda attrs, body: {"query": attrs.get("query") or body.strip()},
    "browse_url": lambda attrs, body: {"url": attrs.get("url") or body.strip()},
    "download_url": lambda attrs, body: {"url": attrs.get("url", ""), "path": attrs.get("filename") or attrs.get("path", "")},
}


def _extract_json_fence_calls(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _JSON_FENCE_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = payload.get("name")
        if not name:
            continue
        calls.append(ToolCall(id=uuid.uuid4().hex, name=name, arguments=payload.get("arguments", {}) or {}))
    return calls


def _extract_legacy_tag_calls(text: str, registry: ToolRegistry) -> list[ToolCall]:
    calls: list[tuple[int, ToolCall]] = []
    seen_aliases: set[str] = set()
    for spec in registry.all_specs():
        for alias in spec.legacy_tag_aliases or (spec.name,):
            if alias in seen_aliases:
                continue
            seen_aliases.add(alias)
            builder = _LEGACY_ARG_BUILDERS.get(spec.name) or _default_builder(list(spec.parameters.get("properties", {})))
            paired = re.compile(rf"<{alias}\b([^>]*)>([\s\S]*?)</{alias}>", re.IGNORECASE)
            for match in paired.finditer(text):
                attrs = dict(_ATTR_RE.findall(match.group(1)))
                body = html.unescape(match.group(2))
                calls.append((match.start(), ToolCall(id=uuid.uuid4().hex, name=spec.name, arguments=builder(attrs, body))))
            self_closing = re.compile(rf"<{alias}\b([^>]*)/>", re.IGNORECASE)
            for match in self_closing.finditer(text):
                attrs = dict(_ATTR_RE.findall(match.group(1)))
                calls.append((match.start(), ToolCall(id=uuid.uuid4().hex, name=spec.name, arguments=builder(attrs, ""))))
    calls.sort(key=lambda pair: pair[0])
    return [call for _, call in calls]


def extract_tool_calls(text: str, registry: ToolRegistry) -> list[ToolCall]:
    """Called once per turn on the FULL accumulated text of a non-native
    provider's response (never on partial/streaming fragments)."""
    fence_calls = _extract_json_fence_calls(text)
    if fence_calls:
        return fence_calls
    return _extract_legacy_tag_calls(text, registry)
