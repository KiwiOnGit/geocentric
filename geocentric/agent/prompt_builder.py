"""System prompt assembly for the in-process agent core.

Deliberately does NOT reuse cli_system_prompt.DEFAULT_SYSTEM_PROMPT's XML-tag
catalog text: that catalog advertises tools (`<apply_patch>`, `<semantic_search>`,
`<embedding_index>`, ...) that were never implemented in server.py, and was
written to teach a pseudo-XML protocol that native tool-calling providers
don't need at all (their tool list is passed structurally, not as prompt
text). A user's own SYSTEMPROMPT.md, if present, is still honored verbatim --
only the *default* fallback text differs, and only fallback-mode providers
(no native tool calling) get a tool catalog appended to the prompt at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from geocentric.cli_system_prompt import system_prompt_path

from .tools import ToolRegistry


def _project_context_files(root: Path) -> list[Path]:
    candidates = [root / "GEOCENTRIC.md", root / "geocentric.md", root / "CLAUDE.md", root / "claude.md"]
    return [path for path in candidates if path.is_file()]

DEFAULT_SYSTEM_PROMPT = """You are Geocentric Code, a local-first AI coding agent running directly on the user's machine.

## Core rules
- Prefer doing the work with tools over describing what you would do.
- When asked to create, edit, read, list, or run files, actually call the relevant tool -- never claim you changed something you did not.
- Keep replies concise, accurate, and action-oriented.
- Ask before destructive or hard-to-reverse actions if you are unsure; the user will also be prompted to approve sensitive tool calls directly.

## Scope
- Greetings and short questions: reply directly, no tools.
- One file requested: create exactly one file, no extra project scaffolding.
- Multi-step coding tasks: use tools as needed, and verify your work (e.g. run the code, read the file back) when useful.
"""

_EFFORT_HINTS = {
    "low": "Be brief. Skip exploratory reasoning; give the most direct correct answer.",
    "medium": "Balance thoroughness with concision.",
    "high": "Think carefully and verify your work before finishing.",
    "max": "Be exhaustive: consider edge cases, verify your work, and double-check tool results before concluding.",
}


class SystemPromptBuilder:
    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()

    def _base_prompt(self) -> str:
        path = system_prompt_path(self.project_root)
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
            except OSError:
                pass
        return DEFAULT_SYSTEM_PROMPT

    def _project_context(self) -> str:
        parts = []
        for file in _project_context_files(self.project_root):
            try:
                content = file.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def build(
        self,
        *,
        effort: str = "medium",
        native_tool_calling: bool = True,
        registry: Optional[ToolRegistry] = None,
    ) -> str:
        sections = [self._base_prompt()]

        effort_hint = _EFFORT_HINTS.get(effort)
        if effort_hint:
            sections.append(f"## Effort level: {effort}\n{effort_hint}")

        project_context = self._project_context()
        if project_context:
            sections.append(f"[Project context]\n{project_context}")

        if not native_tool_calling and registry is not None:
            sections.append(
                "## Tool calling format\n"
                "You do not receive tools as a structured API list. To call a tool, emit a fenced block:\n"
                '```tool_call\n{"name": "<tool name>", "arguments": {...}}\n```\n'
                "Only one tool call per turn will be executed reliably. Available tools:\n"
                + registry.to_prompt_catalog()
            )

        return "\n\n".join(sections)
