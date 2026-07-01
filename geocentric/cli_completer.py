"""Prompt toolkit completers for Geocentric Code CLI."""

from __future__ import annotations

from typing import AsyncGenerator, Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class SlashOnlyCompleter(Completer):
    """Suggest slash commands only when input starts with /."""

    def __init__(self, commands: list[str], descriptions: dict[str, str] | None = None) -> None:
        self.commands = sorted(set(commands))
        self.descriptions = descriptions or {}

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        text = document.text
        if not text.startswith("/"):
            return
        word = text.split()[0] if text else text
        for cmd in self.commands:
            if cmd.lower().startswith(word.lower()):
                desc = self.descriptions.get(cmd, "")
                display = f"{cmd:<16} - {desc}" if desc else cmd
                yield Completion(
                    cmd,
                    start_position=-len(word),
                    display=display,
                )

    async def get_completions_async(
        self, document: Document, complete_event
    ) -> AsyncGenerator[Completion, None]:
        for item in self.get_completions(document, complete_event):
            yield item
