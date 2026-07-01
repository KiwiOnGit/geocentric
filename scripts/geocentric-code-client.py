#!/usr/bin/env python3
"""Geocentric Code — thin remote CLI client (stdlib only, no local install required)."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import sys
import uuid
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_SERVER = "http://127.0.0.1:8000"
SLASH_COMMANDS = sorted([
    "/help", "/exit", "/quit", "/clear", "/status", "/connect", "/server",
    "/model", "/models", "/mode", "/remote-control", "/whatisthis",
])


def _enable_ansi_on_windows() -> bool:
    """Enable ANSI escape sequence support on Windows 10+."""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # Enable VT100 emulation (0x0004)
        mode.value |= 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode))
    except Exception:
        return False


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text or "")


# Enable ANSI support on Windows at startup
_ANSI_SUPPORTED = _enable_ansi_on_windows()


def _write_output(text: str) -> None:
    if _ANSI_SUPPORTED:
        sys.stdout.write(text)
    else:
        sys.stdout.write(_strip_ansi(text))
    sys.stdout.flush()



def ensure_interactive_stdin() -> bool:
    """Reopen TTY when script was piped via curl | python3 - (fixes Windows CMD)."""
    if sys.stdin.isatty():
        return True
    try:
        if sys.platform == "win32":
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        else:
            sys.stdin = open("/dev/tty", "r", encoding="utf-8", errors="replace")
    except OSError:
        return False
    return sys.stdin.isatty()


def _normalize_server(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_SERVER
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url


def _request_json(url: str, method: str = "GET", payload: Optional[dict] = None, token: str = "", timeout: float = 30) -> Any:
    headers = {"Content-Type": "application/json", "X-Geocentric-Client": "cli-remote"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def _extract_delta(packet: dict) -> tuple[str, str]:
    if not isinstance(packet, dict):
        return str(packet or ""), ""
    choices = packet.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}
        return str(delta.get("content") or ""), str(delta.get("reasoning_content") or "")
    return (
        str(packet.get("reply") or packet.get("content") or packet.get("text") or ""),
        str(packet.get("reasoning_content") or packet.get("thinking") or ""),
    )


_NOISE = re.compile(
    r"Proxying request to local Ollama service[^\n]*|"
    r"--- (?:AI|LOCAL AI|API) STREAM (?:START|END) ---[^\n]*",
    re.I,
)


def _filter_noise(text: str) -> str:
    return _NOISE.sub("", text or "")


def _strip_tags(text: str) -> str:
    clean = _filter_noise(text)
    clean = re.sub(r"<status>[\s\S]*?</status>", "", clean, flags=re.I)
    clean = re.sub(
        r"<(?:write_file|edit_file|read_file|run_command|agent_terminal|run_bg_command)\b[^>]*(?:/>|>[\s\S]*?</[^>]+>)",
        "",
        clean,
        flags=re.I,
    )
    return clean.strip()


def _format_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def _estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 4)


def _term_rows() -> int:
    try:
        return shutil.get_terminal_size((100, 40)).lines
    except Exception:
        return 40


def _tool_lines(text: str, seen: set[str], model: str) -> list[str]:
    patterns = [
        (r'<write_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "write_file"),
        (r'<run_command(?:\s+command="([^"]+)")?\s*>([\s\S]*?)(?:</run_command>|$)', "run_command"),
        (r'<agent_terminal\s+command="([^"]+)"', "agent_terminal"),
    ]
    out: list[str] = []
    for pattern, tool in patterns:
        for match in re.finditer(pattern, text or "", re.I):
            detail = next((g for g in match.groups() if g), "").strip().splitlines()[0][:100]
            key = f"{tool}:{detail}"
            if key in seen:
                continue
            seen.add(key)
            label = tool.replace("_", " ")
            out.append(f"  ⚡ {model} Ran: {label}" + (f" → {detail}" if detail else ""))
    return out


class TokenMeter:
    def __init__(self) -> None:
        self.count = 0
        self._row = _term_rows()
        self._on = False

    def start(self) -> None:
        self._row = _term_rows()
        self._on = True
        self._paint()

    def add(self, text: str) -> None:
        self.count += _estimate_tokens(text)
        if self._on:
            self._paint()

    def _paint(self) -> None:
        if _ANSI_SUPPORTED:
            _write_output(f"\033[{self._row};1H\033[2K  ◆ TOKENS: {_format_tokens(self.count)}\033[0m")
        else:
            _write_output(f"  ◆ TOKENS: {_format_tokens(self.count)}\n")

    def stop(self) -> None:
        if self._on:
            self._paint()
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._on = False


class RemoteCLI:
    def __init__(self, server: str, model: str = "", mode: str = "thinking", token: str = "") -> None:
        self.server = _normalize_server(server)
        self.model = model
        self.mode = mode
        self.token = token
        self.messages: list[dict[str, str]] = []
        self.conversation_id = uuid.uuid4().hex
        self.agent_mode = True
        self._seen_tools: set[str] = set()
        self.history: list[tuple[str, str]] = []

    def _url(self, path: str) -> str:
        return f"{self.server}{path if path.startswith('/') else '/' + path}"

    def ping(self) -> bool:
        try:
            _request_json(self._url("/api/status"), timeout=5)
            return True
        except Exception:
            try:
                _request_json(self._url("/api/v1/models"), timeout=5)
                return True
            except Exception:
                return False

    def list_models(self) -> list[str]:
        data = _request_json(self._url("/api/v1/models"), token=self.token, timeout=15)
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def ensure_model(self) -> None:
        try:
            models = self.list_models()
            if not models:
                return
            if not self.model or self.model not in models:
                self.model = next((m for m in models if "agent" in m.lower()), models[0])
        except Exception:
            if not self.model:
                self.model = "geocentric-local"

    def _draw_screen(self) -> None:
        cols, _ = shutil.get_terminal_size((100, 40))
        inner = max(40, cols - 6)
        line = "─" * inner
        if _ANSI_SUPPORTED:
            _write_output("\033[2J\033[H")
        else:
            print()
        print(f"  ╭{line}╮")
        print(f"  │  Geocentric Code (remote){' ' * max(1, inner - 26)}│")
        print(f"  │  {self.server[:inner-2]:<{inner-2}} │")
        print(f"  │  {self.model} · {self.mode}{' ' * max(1, inner - len(self.model) - len(self.mode) - 4)}│")
        print(f"  ╰{line}╯")
        print()
        for role, text in self.history[-10:]:
            if role == "user":
                print(f"  ❯ {text}")
            else:
                print(f"  {self.model} › {text[:cols-12]}")
            print()
        sys.stdout.flush()

    def stream_chat(self, user_text: str) -> str:
        payload = {
            "model": self.model,
            "mode": self.mode,
            "modelMode": self.mode,
            "searchWeb": False,
            "conversationId": self.conversation_id,
            "agentMode": self.agent_mode,
            "projectPath": os.getcwd(),
            "stream": True,
            "messages": self.messages + [{"role": "user", "content": user_text}],
        }
        headers = {"Content-Type": "application/json", "X-Geocentric-Client": "cli-remote"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(
            self._url("/api/chat"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        raw = ""
        last_visible = 0
        self._seen_tools.clear()
        meter = TokenMeter()
        print(f"\n  {self.model} › ", end="", flush=True)
        meter.start()

        with urlopen(req, timeout=600) as resp:
            if "text/event-stream" not in (resp.headers.get("Content-Type") or ""):
                body = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                raw = _filter_noise(_extract_delta(body)[0])
                meter.stop()
                clean = _strip_tags(raw)
                if clean:
                    print(clean)
                return clean

            buffer = ""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    packet, buffer = buffer.split("\n\n", 1)
                    for line in packet.split("\n"):
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data_str)
                        except Exception:
                            continue
                        content, reasoning = _extract_delta(parsed)
                        content = _filter_noise(content)
                        reasoning = _filter_noise(reasoning)
                        if reasoning:
                            meter.add(reasoning)
                        if not content:
                            continue
                        raw += content
                        meter.add(content)
                        for tl in _tool_lines(raw, self._seen_tools, self.model):
                            meter.stop()
                            print(f"\n{tl}")
                            meter.start()
                        visible = _strip_tags(raw)
                        if len(visible) > last_visible:
                            delta = visible[last_visible:]
                            last_visible = len(visible)
                            if delta:
                                meter.stop()
                                _write_output(delta)
                                meter.start()

        meter.stop()
        if last_visible == 0:
            print()
        return _strip_tags(raw)

    def handle_slash(self, line: str) -> bool:
        parts = line.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in {"/help", "/?"}:
            print("\n  Commands:", ", ".join(SLASH_COMMANDS))
            return True
        if cmd in {"/exit", "/quit", "/q"}:
            print("  Goodbye.")
            raise SystemExit(0)
        if cmd == "/clear":
            self.messages.clear()
            self.history.clear()
            self.conversation_id = uuid.uuid4().hex
            return True
        if cmd == "/status":
            print(f"  Server: {self.server}  Model: {self.model}  Online: {self.ping()}")
            return True
        if cmd == "/connect" and args:
            self.server = _normalize_server(args[0])
            self.ensure_model()
            return True
        if cmd == "/model" and args:
            self.model = args[0]
            return True
        if cmd == "/remote-control":
            print(f"  curl -s {self.server}/api/cli/client -o gcc.py && python gcc.py --server {self.server}")
            return True
        return True

    def repl(self) -> None:
        if not ensure_interactive_stdin():
            raise SystemExit(
                "No interactive terminal. Save the client first:\n"
                f"  curl -s {self.server}/api/cli/client -o geocentric-code.py\n"
                f"  python geocentric-code.py --server {self.server}"
            )

        if not self.ping():
            raise SystemExit(f"Could not reach {self.server}. Start the host with ./run.sh first.")
        self.ensure_model()

        if sys.platform != "win32":
            try:
                import readline

                def complete(text: str, state: int) -> Optional[str]:
                    buf = readline.get_line_buffer()
                    if not buf.startswith("/"):
                        return None
                    matches = [c for c in SLASH_COMMANDS if c.startswith(text or "/")]
                    return matches[state] if state < len(matches) else None

                readline.set_completer(complete)
                readline.parse_and_bind("tab: complete")
            except ImportError:
                pass

        while True:
            self._draw_screen()
            try:
                line = input("  ❯ ").strip()
            except KeyboardInterrupt:
                print("\n  (Ctrl+C — type /exit to quit)")
                continue
            except EOFError:
                print("\n  (disconnected — type /exit to quit or reconnect)")
                continue

            if not line:
                continue
            if line.startswith("/"):
                self.handle_slash(line)
                continue
            try:
                reply = self.stream_chat(line)
                self.messages.append({"role": "user", "content": line})
                self.messages.append({"role": "assistant", "content": reply})
                if reply:
                    self.history.append(("user", line))
                    self.history.append(("assistant", reply))
            except HTTPError as exc:
                print(f"  Error {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
            except URLError as exc:
                print(f"  Connection error: {exc.reason}")
            except Exception as exc:
                print(f"  Error: {exc}")


def main() -> None:
    p = argparse.ArgumentParser(description="Geocentric Code remote CLI (no local install)")
    p.add_argument("--server", default=os.environ.get("GEOCENTRIC_SERVER", DEFAULT_SERVER))
    p.add_argument("--model", default="")
    p.add_argument("--mode", choices=["thinking", "instant"], default="thinking")
    p.add_argument("--token", default="")
    args = p.parse_args()
    RemoteCLI(args.server, args.model, args.mode, args.token).repl()


if __name__ == "__main__":
    main()
