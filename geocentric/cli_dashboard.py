"""Geocentric Code CLI — Claude Code-style terminal UI."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Literal

from geocentric import __version__
from geocentric.cli_ui import C, format_tokens, paint, strip_ansi, terminal_size, render_markdown

try:
    from prompt_toolkit.formatted_text import FormattedText
except Exception:  # pragma: no cover - prompt_toolkit optional
    FormattedText = None


LineKind = Literal["user", "assistant", "tool", "status", "thinking", "error", "plan"]

_EFFORT_LABELS = {"low": "low", "medium": "medium", "high": "high", "max": "xhigh"}

_EARTH_ART = (
    "       .-'-.",
    "      /     \\",
    "     |  @@@  |",
    "      \\     /",
    "       '-.-'",
)


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _wrap(text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


@dataclass
class HistoryLine:
    kind: LineKind
    text: str
    dim: bool = False


@dataclass
class ClaudeCodeDashboard:
    model: str
    mode: str
    server: str
    effort: str = "medium"
    cwd: str = field(default_factory=os.getcwd)
    history: list[HistoryLine] = field(default_factory=list)
    token_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    live_status: str = ""
    thinking: bool = False
    thinking_detail: str = ""
    reasoning_tokens: int = 0
    _spinner_i: int = 0
    _banner_shown: bool = False
    _streaming: bool = False
    _thinking_active: bool = False

    SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    streaming_text: str = ""

    def enter(self) -> None:
        if not self._banner_shown:
            self.print_welcome_banner()
            self._banner_shown = True

    def leave(self, *, reason: str = "exit") -> None:
        self.clear_thinking()
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _inner_width(self) -> int:
        cols, _ = terminal_size()
        return max(60, cols - 2)

    def _effort_display(self) -> str:
        return _EFFORT_LABELS.get(self.effort, self.effort)

    def set_effort(self, effort: str) -> None:
        self.effort = (effort or "medium").strip().lower() or "medium"
        if self._banner_shown:
            self.add("status", f"{self.model} with {self._effort_display()} effort · Local", dim=True)

    def print_welcome_banner(self) -> None:
        inner = self._inner_width()
        title = f" Geocentric Code v{__version__} "
        top = "╭───" + title + "─" * max(1, inner - len(title) - 3) + "╮"

        left_w = max(28, inner // 2 - 2)
        right_w = max(28, inner - left_w - 3)

        model_line = f"{self.model} with {_EFFORT_LABELS.get(self.effort, self.effort)} effort · Local"
        cwd_line = self.cwd.replace(os.path.expanduser("~"), "~")

        right_body: list[str] = []
        right_body.extend(_wrap("Tips for getting started", right_w))
        right_body.extend(_wrap("Run /init to create a GEOCENTRIC.md file with instructions for the agent", right_w))
        right_body.extend(_wrap("Edit SYSTEMPROMPT.md in the project root to customize agent behavior", right_w))
        right_body.append("─" * min(right_w, 70))
        right_body.extend(_wrap("What's new", right_w))
        right_body.extend(_wrap(
            "Geocentric Code — local AI coding agent powered by Ollama on your machine",
            right_w,
        ))
        right_body.extend(_wrap(
            "Workspace tools run in your project folder when agent mode is on",
            right_w,
        ))
        right_body.extend(_wrap(
            "Use /model to switch models · /help for commands · /doctor to verify setup",
            right_w,
        ))

        left_rows: list[str] = ["", "Welcome back!", ""] + list(_EARTH_ART) + ["", _truncate(model_line, left_w), _truncate(cwd_line, left_w)]

        height = max(len(left_rows), len(right_body))
        while len(left_rows) < height:
            left_rows.append("")
        while len(right_body) < height:
            right_body.append("")

        earth_start = 3
        earth_end = earth_start + len(_EARTH_ART) - 1

        print()
        print(paint(top, C.GRAY))

        for row_i in range(height):
            left = left_rows[row_i]
            right = right_body[row_i]

            if row_i == 1 or earth_start <= row_i <= earth_end or row_i in (len(_EARTH_ART) + 4, len(_EARTH_ART) + 5):
                lp = left.center(left_w) if left else ""
            else:
                lp = _truncate(left, left_w)
            rp = _truncate(right, right_w)
            lp_pad = " " * (left_w - len(lp))
            rp_pad = " " * (right_w - len(rp))

            if row_i == 1:
                lp_painted = paint(lp, C.BOLD, C.BRIGHT_WHITE)
            elif earth_start <= row_i <= earth_end:
                lp_painted = paint(lp, C.SOFT_GREEN, C.BOLD)
            elif row_i == len(_EARTH_ART) + 4:
                lp_painted = paint(lp, C.SOFT_BLUE)
            elif row_i == len(_EARTH_ART) + 5:
                lp_painted = paint(lp, C.DIM, C.GRAY)
            else:
                lp_painted = paint(lp, C.GRAY) if lp else ""

            if right.startswith("Tips"):
                rp_painted = paint(rp, C.BOLD, C.BRIGHT_WHITE)
            elif right.startswith("What's"):
                rp_painted = paint(rp, C.BOLD, C.BRIGHT_WHITE)
            elif right.startswith("─"):
                rp_painted = paint(rp, C.GRAY)
            else:
                rp_painted = paint(rp, C.GRAY)

            print(
                paint("│", C.GRAY)
                + lp_painted
                + lp_pad
                + paint(" │ ", C.GRAY)
                + rp_painted
                + rp_pad
                + paint("│", C.GRAY)
            )

        print(paint("╰" + "─" * inner + "╯", C.GRAY))
        print()

    def _footer(self, *, auto_accept: bool = False) -> object:
        effort = self._effort_display()
        left = [
            ("dim", "? for shortcuts"),
            ("", " · "),
            ("dim", "← for agents"),
        ]
        if auto_accept:
            left.extend([("", " · "), ("bold", "AUTO ACCEPT")])
        right = [
            ("fg:ansigreen", f"◉ {effort}"),
            ("", " · "),
            ("dim", "/effort"),
        ]
        if FormattedText is not None:
            return FormattedText([("", "  ")] + left + [("", " ")] + right)
        return "  " + "".join(part for _, part in left + right)

    def run_indexing(self) -> None:
        """No-op."""

    def add(self, kind: LineKind, text: str, *, dim: bool = False) -> None:
        clean = (text or "").strip()
        if not clean:
            return
        self.history.append(HistoryLine(kind=kind, text=clean, dim=dim or kind == "status"))
        if len(self.history) > 200:
            self.history = self.history[-200:]
        self._print_history_line(HistoryLine(kind=kind, text=clean, dim=dim or kind == "status"))

    def _print_history_line(self, item: HistoryLine) -> None:
        text = item.text
        if text.startswith("* ") and not text.startswith("*  "):
            text = text.replace("\n* ", "\n  * ", 1)
        if item.kind == "user":
            print(paint("❯ ", C.ORANGE, C.BOLD) + paint(text, C.BRIGHT_WHITE))
        elif item.kind == "assistant":
            header = paint(f"  {self.model}", C.BOLD, C.WHITE) + paint(" › ", C.GRAY)
            # Render markdown for assistant responses
            rendered = render_markdown(text)
            lines = rendered.splitlines() or [""]
            for i, line in enumerate(lines):
                body = line if item.dim else line
                print((header + body) if i == 0 else ("    " + body))
        elif item.kind == "tool":
            print(paint(f"  ⚙ {text}", C.YELLOW))
        elif item.kind == "error":
            print(paint(f"  ✕ {text}", C.RED))
        else:
            print(paint(f"  {text}", C.SOFT_BLUE if not item.dim else C.GRAY))
        print()

    def set_thinking(self, active: bool) -> None:
        self.thinking = active
        if not active:
            self.clear_thinking()
        elif active:
            self._spinner_i = (self._spinner_i + 1) % len(self.SPINNER)
            self._draw_thinking_line()

    def update_thinking(self, *, detail: str = "", reasoning_tokens: int | None = None, usage: dict | None = None, token_count: int | None = None) -> None:
        if detail:
            self.thinking_detail = detail
        if usage:
            self.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            self.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            self.token_count = int(usage.get("total_tokens", self.prompt_tokens + self.completion_tokens) or 0)
        if token_count is not None:
            self.token_count = max(0, int(token_count))
        if reasoning_tokens is not None:
            self.reasoning_tokens = reasoning_tokens
        self.thinking = True
        self._thinking_active = True
        self._spinner_i = (self._spinner_i + 1) % len(self.SPINNER)
        self._draw_thinking_line()

    def clear_thinking(self) -> None:
        if self._thinking_active:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        self._thinking_active = False
        self.thinking = False
        self.thinking_detail = ""
        self.reasoning_tokens = 0

    def _draw_thinking_line(self) -> None:
        spin = self.SPINNER[self._spinner_i]
        detail = _truncate(self.thinking_detail or "…", max(20, self._inner_width() - 28))
        tokens = format_tokens(max(self.token_count, self.reasoning_tokens))
        line = (
            paint(f"  {spin} ", C.SOFT_GREEN)
            + paint("Thinking", C.SOFT_GREEN, C.BOLD)
            + paint(f" • {detail}  ", C.GRAY)
            + paint(f"Tokens: {tokens}", C.DIM)
        )
        sys.stdout.write("\r\033[2K" + line)
        sys.stdout.flush()
        self._thinking_active = True

    def set_tokens(self, n: int) -> None:
        self.token_count = n
        self.prompt_tokens = max(0, n // 2)
        self.completion_tokens = max(0, n - self.prompt_tokens)

    def add_tokens(self, n: int) -> None:
        self.token_count += n

    def update_footer_only(self) -> None:
        pass

    def set_streaming(self, text: str) -> None:
        self.streaming_text = text or ""
        self._streaming = True

    def clear_streaming(self) -> None:
        if self._streaming:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        self._streaming = False
        self.streaming_text = ""

    def finish_assistant(self, text: str, *, dim: bool = False) -> None:
        self.clear_thinking()
        self.clear_streaming()
        if text.strip():
            self.add("assistant", text, dim=dim)

    def add_turn(self, role: str, text: str) -> None:
        kind: LineKind = "user" if role == "user" else "assistant"
        self.add(kind, text)

    def set_status(self, msg: str) -> None:
        self.live_status = msg

    def redraw(self) -> None:
        pass

    def render(self) -> None:
        if self.thinking:
            self._draw_thinking_line()

    def start(self) -> None:
        self.enter()

    def stop(self) -> None:
        self.leave()

    def show_error_panel(self, code: str, message: str) -> None:
        self.clear_thinking()
        w = min(self._inner_width(), 72)
        print()
        print(paint(f" ┌{'─' * (w + 2)}┐", C.RED))
        print(paint(f" │ Error {code:<{w - 7}}│", C.RED, C.BOLD))
        print(paint(f" ├{'─' * (w + 2)}┤", C.RED))
        for line in _wrap(message, w):
            print(paint(f" │ {line:<{w}} │", C.RED))
        print(paint(f" └{'─' * (w + 2)}┘", C.RED))
        print()
