"""Geocentric Code CLI — terminal UI theme, formatting, and stream rendering."""

from __future__ import annotations

import html
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from geocentric.cli_command_docs import CommandDoc


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDER = "\033[4m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BRIGHT_WHITE = "\033[97m"
    ORANGE = "\033[38;5;208m"
    SOFT_BLUE = "\033[38;5;117m"
    SOFT_GREEN = "\033[38;5;114m"
    SOFT_PURPLE = "\033[38;5;141m"
    BG_DARK = "\033[48;5;235m"
    BG_PANEL = "\033[48;5;236m"


def supports_color() -> bool:
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


def paint(text: str, *codes: str) -> str:
    if not supports_color() or not codes:
        return text
    return "".join(codes) + text + C.RESET


def terminal_size() -> tuple[int, int]:
    try:
        return shutil.get_terminal_size((100, 40))
    except Exception:
        return 100, 40


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text or "")


_STREAM_NOISE = re.compile(
    r"Proxying request to local Ollama service[^\n]*|"
    r"Model requested web search[^\n]*|"
    r"\[AI REASONING (?:START|END)\][^\n]*|"
    r"--- (?:AI|LOCAL AI|API OLLAMA|API LOCAL MODEL) STREAM (?:START|END) ---[^\n]*",
    re.IGNORECASE,
)


def filter_stream_noise(text: str) -> str:
    return _STREAM_NOISE.sub("", text or "")


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def enter_alt_screen() -> None:
    if supports_color():
        sys.stdout.write("\033[?1049h\033[2J\033[H")
        sys.stdout.flush()


def leave_alt_screen() -> None:
    if supports_color():
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()


def move_cursor(row: int, col: int = 1) -> None:
    sys.stdout.write(f"\033[{row};{col}H")


def clear_line_at(row: int) -> None:
    move_cursor(row)
    sys.stdout.write("\033[2K")
    sys.stdout.flush()


def format_tokens(count: int) -> str:
    if count >= 1_000_000:
        val = count / 1_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    if count >= 1000:
        val = count / 1000
        return f"{val:.1f}k".replace(".0k", "k")
    return str(count)


def estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 4)


@dataclass
class ToolAction:
    tool: str
    detail: str
    raw: str = ""

    def format_line(self, model_name: str) -> str:
        label = self.tool.replace("_", " ")
        if self.detail:
            return paint(f"  ⚡ {model_name} Ran: {label} → {self.detail}", C.SOFT_PURPLE, C.BOLD)
        return paint(f"  ⚡ {model_name} Ran: {label}", C.SOFT_PURPLE, C.BOLD)


_TOOL_PATTERNS: list[tuple[str, str, int]] = [
    (r'<write_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "write_file", 1),
    (r'<edit_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "edit_file", 1),
    (r'<read_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "read_file", 1),
    (r'<delete_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "delete_file", 1),
    (r'<run_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "run_file", 1),
    (r'<agent_terminal\s+command="([^"]+)"', "agent_terminal", 1),
    (r'<run_command(?:\s+command="([^"]+)")?\s*>([\s\S]*?)(?:</run_command>|$)', "run_command", 0),
    (r'<run_bg_command(?:\s+command="([^"]+)")?\s*>([\s\S]*?)(?:</run_bg_command>|$)', "run_bg_command", 0),
    (r'<install_package\s+name="([^"]+)"', "install_package", 1),
    (r'<http_request\s+url="([^"]+)"', "http_request", 1),
    (r'<browse_url\s+url="([^"]+)"', "browse_url", 1),
    (r'<port_check\b[^>]*port="([^"]+)"', "port_check", 1),
    (r'<list_directory\b[^>]*\b(?:path|dir)="([^"]+)"', "list_directory", 1),
    (r'<glob\b[^>]*pattern="([^"]+)"', "glob", 1),
    (r'<grep\b[^>]*pattern="([^"]+)"', "grep", 1),
    (r'<update_roadmap\b', "update_roadmap", -1),
    (r'<view_project_tree\b', "view_project_tree", -1),
    (r'<system_info\b', "system_info", -1),
]


def extract_tool_actions(text: str, seen: set[str]) -> list[ToolAction]:
    src = text or ""
    found: list[tuple[int, ToolAction]] = []
    for pattern, tool, group_idx in _TOOL_PATTERNS:
        for match in re.finditer(pattern, src, re.IGNORECASE):
            if group_idx == -1:
                detail = ""
            else:
                groups = match.groups()
                detail = ""
                for g in groups:
                    if g:
                        detail = html.unescape(g).strip().splitlines()[0]
                        break
            key = f"{tool}:{detail}:{match.start()}"
            if key in seen:
                continue
            if len(detail) > 100:
                detail = detail[:97] + "..."
            found.append((match.start(), ToolAction(tool=tool, detail=detail, raw=match.group(0)[:120])))
    found.sort(key=lambda x: x[0])
    actions: list[ToolAction] = []
    for _, action in found:
        key = f"{action.tool}:{action.detail}"
        if key not in seen:
            seen.add(key)
            seen.add(f"{action.tool}:{action.detail}:{action.raw}")
            actions.append(action)
    return actions


def strip_internal_tags(text: str) -> str:
    clean = filter_stream_noise(text or "")
    # Remove thinking tags completely (both opening/closing and self-closing)
    clean = re.sub(r"<think>[\s\S]*?</think>", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<think\s*/?>", "", clean, flags=re.IGNORECASE)
    # Remove plan tags
    clean = re.sub(r"<plan>[\s\S]*?</plan>", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<plan\s*/?>", "", clean, flags=re.IGNORECASE)
    # Remove status tags
    clean = re.sub(r"<status>[\s\S]*?</status>", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<chat_title\b[^>]*>[\s\S]*?</chat_title>", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<usage_notice\b[^>]*/>", "", clean, flags=re.IGNORECASE)
    tag_patterns = [
        r"<write_file\b[\s\S]*?</write_file>",
        r"<edit_file\b[\s\S]*?</edit_file>",
        r"<read_file\b[^>]*/?>",
        r"<run_command\b[^>]*>[\s\S]*?</run_command>",
        r"<run_command\b[^>]*/?>",
        r"<agent_terminal\b[\s\S]*?</agent_terminal>",
        r"<agent_terminal\b[^>]*/?>",
        r"<run_bg_command\b[\s\S]*?</run_bg_command>",
        r"<list_directory\b[^>]*/?>",
        r"<glob\b[^>]*/?>",
        r"<grep\b[^>]*/?>",
        r"<(?:delete_file|run_file|browse_url|install_package|http_request|port_check|update_roadmap|view_project_tree|system_info)\b[^>]*/?>",
    ]
    for pat in tag_patterns:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    return clean.strip()


def latest_status(text: str) -> str:
    matches = re.findall(r"<status>([\s\S]*?)</status>", text or "", flags=re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    partial = re.search(r"<status>([^<]*)$", text or "", flags=re.IGNORECASE)
    return partial.group(1).strip() if partial else ""


def render_markdown(text: str) -> str:
    """Convert markdown to terminal-formatted text with colors."""
    if not text:
        return ""
    
    lines = text.split("\n")
    output = []
    in_code_block = False
    code_lang = ""
    code_lines = []
    
    for line in lines:
        # Handle code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                # End code block
                code_content = "\n".join(code_lines)
                formatted = paint(code_content, C.CYAN)
                output.append(formatted)
                in_code_block = False
                code_lines = []
                code_lang = ""
            else:
                # Start code block
                code_lang = line.strip()[3:].strip()
                in_code_block = True
            continue
        
        if in_code_block:
            code_lines.append(line)
            continue
        
        # Headers
        if line.startswith("### "):
            output.append(paint(line[4:], C.BOLD, C.YELLOW))
            continue
        elif line.startswith("## "):
            output.append(paint(line[3:], C.BOLD, C.CYAN))
            continue
        elif line.startswith("# "):
            output.append(paint(line[2:], C.BOLD, C.WHITE))
            continue
        
        # List items
        if line.lstrip().startswith("- "):
            indent = len(line) - len(line.lstrip())
            item = line.lstrip()[2:]
            formatted_item = "  " * (indent // 2) + "• " + item
            output.append(formatted_item)
            continue
        
        if line.lstrip().startswith("* "):
            indent = len(line) - len(line.lstrip())
            item = line.lstrip()[2:]
            formatted_item = "  " * (indent // 2) + "• " + item
            output.append(formatted_item)
            continue
        
        # Bold and italic formatting within lines
        formatted_line = line
        # Replace **bold** with bold
        formatted_line = re.sub(r"\*\*([^\*]+)\*\*", lambda m: paint(m.group(1), C.BOLD), formatted_line)
        # Replace *italic* with italic (but not **bold**)
        formatted_line = re.sub(r"(?<!\*)\*([^\*]+)\*(?!\*)", lambda m: paint(m.group(1), C.ITALIC), formatted_line)
        # Replace `code` with cyan
        formatted_line = re.sub(r"`([^`]+)`", lambda m: paint(m.group(1), C.CYAN), formatted_line)
        
        output.append(formatted_line)
    
    # Handle unclosed code block
    if in_code_block and code_lines:
        code_content = "\n".join(code_lines)
        formatted = paint(code_content, C.CYAN)
        output.append(formatted)
    
    return "\n".join(output)


class TokenCounter:
    """Single-line in-place token meter using carriage return (no stacked lines)."""

    def __init__(self) -> None:
        self.output_tokens = 0
        self.reasoning_tokens = 0
        self._active = False

    @property
    def total(self) -> int:
        return self.output_tokens + self.reasoning_tokens

    def begin(self) -> None:
        self._active = True
        self._draw()

    def add_output(self, text: str) -> None:
        self.output_tokens += estimate_tokens(text)

    def add_reasoning(self, text: str) -> None:
        self.reasoning_tokens += estimate_tokens(text)

    def refresh(self, *, thinking: bool = False) -> None:
        if self._active:
            self._draw(thinking=thinking)

    def _label(self, *, thinking: bool = False) -> str:
        parts = [f"TOKENS: {format_tokens(self.total)}"]
        if thinking and self.reasoning_tokens:
            parts.append(f"thinking {format_tokens(self.reasoning_tokens)}")
        return paint("  ◆ ", C.CYAN) + paint("  ·  ".join(parts), C.GRAY, C.BOLD)

    def _draw(self, *, thinking: bool = False) -> None:
        sys.stdout.write("\r\033[2K" + self._label(thinking=thinking))
        sys.stdout.flush()

    def pause(self) -> None:
        """Move cursor to next line before printing permanent output."""
        if self._active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._active = False

    def resume(self) -> None:
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def finish(self) -> None:
        if self._active:
            self._draw()
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._active = False


@dataclass
class ChatTurn:
    role: str
    text: str


@dataclass
class TerminalUI:
    """Full-terminal renderer with alternate screen and conversation history."""

    server: str
    model: str
    mode: str
    session_name: str = "default"
    turns: list[ChatTurn] = field(default_factory=list)
    status_message: str = ""
    _alt: bool = False

    def start(self) -> None:
        enter_alt_screen()
        self._alt = True
        self.redraw()

    def stop(self) -> None:
        if self._alt:
            leave_alt_screen()
            self._alt = False

    def add_turn(self, role: str, text: str) -> None:
        clean = strip_internal_tags(text).strip()
        if clean:
            self.turns.append(ChatTurn(role=role, text=clean))
            if len(self.turns) > 40:
                self.turns = self.turns[-40:]

    def set_status(self, msg: str) -> None:
        self.status_message = msg
        self.redraw()

    def redraw(self) -> None:
        cols, rows = terminal_size()
        inner = max(40, cols - 6)
        line = "─" * inner

        out: list[str] = []
        out.append("")
        out.append(paint(f"  ╭{line}╮", C.GRAY))
        title = paint("  Geocentric Code", C.BOLD, C.ORANGE)
        pad = max(1, inner - 17)
        out.append(paint("  │", C.GRAY) + title + paint(" " * pad + "│", C.GRAY))
        sub = paint("  AI coding agent", C.DIM, C.GRAY)
        out.append(paint("  │", C.GRAY) + sub + paint(" " * max(1, inner - 17) + "│", C.GRAY))
        out.append(paint(f"  ├{line}┤", C.GRAY))

        meta = f"{self.model} · {self.mode} · {self.server}"
        if len(meta) > inner - 2:
            meta = meta[: inner - 5] + "..."
        out.append(paint("  │ ", C.GRAY) + paint(meta, C.SOFT_BLUE) + paint(" " * max(1, inner - len(meta)) + "│", C.GRAY))
        sess = f"session: {self.session_name}"
        out.append(paint("  │ ", C.GRAY) + paint(sess, C.DIM) + paint(" " * max(1, inner - len(sess)) + "│", C.GRAY))
        out.append(paint(f"  ╰{line}╯", C.GRAY))
        out.append("")

        for turn in self.turns[-12:]:
            if turn.role == "user":
                out.append(paint("  ❯ ", C.ORANGE, C.BOLD) + paint(turn.text, C.BRIGHT_WHITE))
            else:
                out.append(paint(f"  {self.model}", C.BOLD, C.WHITE) + paint(" › ", C.GRAY) + turn.text)
            out.append("")

        if self.status_message:
            out.append(paint(f"  {self.status_message}", C.SOFT_BLUE))
            out.append("")

        clear_screen()
        body = "\n".join(out)
        print(body)
        footer = paint("  ? for shortcuts · /help for commands", C.DIM)
        move_cursor(rows)
        sys.stdout.write(footer)
        sys.stdout.flush()


def print_banner(server: str, model: str, mode: str, session_name: str = "") -> None:
    TerminalUI(server, model, mode, session_name).redraw()


def print_command_explanation(command: str, doc: "CommandDoc") -> None:
    print()
    print(paint(f"  {command}", C.BOLD, C.SOFT_GREEN))
    print(paint("  ─" * 30, C.GRAY))
    print(paint("  What", C.BOLD, C.ORANGE) + paint(f"   {doc.what}", C.BRIGHT_WHITE))
    print(paint("  Why", C.BOLD, C.ORANGE) + paint(f"    {doc.why}", C.GRAY))
    print(paint("  When", C.BOLD, C.ORANGE) + paint(f"   {doc.when}", C.GRAY))
    print(paint("  How", C.BOLD, C.ORANGE) + paint(f"    {doc.how}", C.GRAY))
    if doc.examples:
        print(paint("  Examples", C.BOLD, C.SOFT_BLUE))
        for ex in doc.examples:
            print(paint(f"    {ex}", C.SOFT_GREEN))
    print()


def print_help_section(title: str, rows: list[tuple[str, str]]) -> None:
    print(paint(f"\n  {title}", C.BOLD, C.ORANGE))
    for cmd, desc in rows:
        print(f"  {paint(cmd, C.SOFT_GREEN):<28} {paint(desc, C.GRAY)}")


def print_command_suggestions(prefix: str, matches: list[str], max_show: int = 8) -> None:
    if not matches or not prefix.startswith("/"):
        return
    shown = matches[:max_show]
    more = len(matches) - len(shown)
    print(paint("\n  Matching commands:", C.DIM))
    for cmd in shown:
        print(f"    {paint(cmd, C.SOFT_GREEN)}")
    if more > 0:
        print(paint(f"    … and {more} more", C.DIM))


def fuzzy_match_commands(prefix: str, commands: list[str]) -> list[str]:
    p = prefix.lower().strip()
    if not p.startswith("/"):
        return []
    if p == "/":
        return sorted(commands)
    exact = [c for c in commands if c.lower().startswith(p)]
    if exact:
        return sorted(exact)
    body = p[1:]
    scored: list[tuple[int, str]] = []
    for cmd in commands:
        name = cmd[1:]
        if body in name or name.startswith(body):
            scored.append((name.index(body) if body in name else 0, cmd))
        elif all(ch in name for ch in body):
            scored.append((100 + len(name), cmd))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _, c in scored[:12]]


def format_assistant_header(model: str) -> str:
    return paint(f"\n  {model}", C.BOLD, C.BRIGHT_WHITE) + paint(" › ", C.GRAY)


def format_user_prompt() -> str:
    return paint("  ❯ ", C.ORANGE, C.BOLD)


def format_error(msg: str) -> str:
    return paint(f"  ✗ {msg}", C.RED)


def format_success(msg: str) -> str:
    return paint(f"  ✓ {msg}", C.SOFT_GREEN)


def format_info(msg: str) -> str:
    return paint(f"  · {msg}", C.SOFT_BLUE)
