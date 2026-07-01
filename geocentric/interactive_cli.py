"""Geocentric Code CLI — interactive terminal agent (Claude Code style)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from http.client import IncompleteRead
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from geocentric.cli_commands import COMMAND_REGISTRY, all_command_names, handle_slash
from geocentric.cli_completer import SlashOnlyCompleter
from geocentric.cli_dashboard import ClaudeCodeDashboard
from geocentric.cli_session import SessionState, load_conversation_history, save_checkpoint, save_conversation_history, save_session
from geocentric.cli_system_prompt import load_system_prompt
from geocentric.cli_ui import (
    C,
    estimate_tokens,
    extract_tool_actions,
    filter_stream_noise,
    latest_status,
    paint,
    strip_internal_tags,
)

DEFAULT_SERVER = os.environ.get("GEOCENTRIC_SERVER", "http://127.0.0.1:8000")
CONFIG_PATH = os.path.expanduser("~/.geocentric/cli.json")


class CliConfig:
    def __init__(self) -> None:
        self.server: str = DEFAULT_SERVER
        self.model: str = "geocentric-local"
        self.model_mode: str = "thinking"
        self.token: str = ""
        self.agent_mode: bool = True
        self.search_web: bool = False
        self.conversation_id: str = uuid.uuid4().hex

    @classmethod
    def load(cls) -> "CliConfig":
        cfg = cls()
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for key, value in data.items():
                    if hasattr(cfg, key) and value is not None:
                        setattr(cfg, key, value)
        except Exception:
            pass
        return cfg

    def save(self) -> None:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "server": self.server,
                    "model": self.model,
                    "model_mode": self.model_mode,
                    "token": self.token,
                    "agent_mode": self.agent_mode,
                    "search_web": self.search_web,
                },
                fh,
                indent=2,
            )


def _normalize_server(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_SERVER
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url


def _request_json(url: str, method: str = "GET", payload: Optional[dict] = None, token: str = "", timeout: float = 30) -> Any:
    headers = {"Content-Type": "application/json", "X-Geocentric-Client": "cli"}
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


class InteractiveCLI:
    _normalize_server = staticmethod(_normalize_server)

    def __init__(self, config: CliConfig, *, continue_chat: Optional[str] = None, force: bool = False):
        self.config = config
        self.config.server = _normalize_server(config.server)
        self.messages: list[dict[str, str]] = []
        self.session = SessionState(
            conversation_id=config.conversation_id,
            model=config.model,
            model_mode=config.model_mode,
        )
        self.pending_skill: str = ""
        self.pending_directive: str = ""
        self.btw_message: str = ""
        self._seen_tools: set[str] = set()
        self._commands = all_command_names()
        self._cmd_desc = {c.name: c.description for c in COMMAND_REGISTRY}
        self.dash = ClaudeCodeDashboard(
            model=config.model,
            mode=config.model_mode,
            server=config.server,
            effort=self.session.effort,
            cwd=os.getcwd(),
        )
        self._prompt_session = None
        self._force_mode = force
        self._auto_accept = False
        self._continue_chat = continue_chat

    def _url(self, path: str) -> str:
        return f"{self.config.server}{path if path.startswith('/') else '/' + path}"

    def api_get(self, path: str) -> Any:
        return _request_json(self._url(path), token=self.config.token, timeout=15)

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
        data = _request_json(self._url("/api/v1/models"), token=self.config.token, timeout=15)
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def _sync_dash(self) -> None:
        self.dash.model = self.config.model
        self.dash.mode = self.config.model_mode
        self.dash.server = self.config.server
        self.dash.effort = self.session.effort
        self.dash.set_tokens(self.session.token_usage)

    def _load_resume_context(self) -> None:
        if not self._continue_chat:
            return
        history = load_conversation_history(self._continue_chat)
        if not history:
            return
        self.messages = list(history)
        self.session.messages = list(history)
        self.session.conversation_id = self._continue_chat
        self.config.conversation_id = self._continue_chat
        save_conversation_history(self._continue_chat, history)

    def _should_prompt_for_tool(self, tool_name: str) -> bool:
        return tool_name in {"run_command", "run_shell", "run_bg_command", "run_python", "run_node", "run_binary", "agent_terminal", "write_file", "append_file", "edit_file", "delete_file", "move_file", "apply_patch"}

    def _prompt_for_tool_action(self, action) -> bool:
        if self._force_mode or self._auto_accept:
            self.dash.add("status", f"Auto-accepted {action.tool}")
            return True
        print()
        print(paint("┌" + "─" * 72 + "┐", C.SOFT_PURPLE, C.BOLD))
        print(paint("│ Approve tool action", C.SOFT_PURPLE, C.BOLD))
        print(paint("├" + "─" * 72 + "┤", C.SOFT_PURPLE, C.BOLD))
        for line in (action.raw or action.detail or action.tool).splitlines() or [""]:
            print(paint(f"│ {line[:70]:<70} │", C.BRIGHT_WHITE))
        print(paint("└" + "─" * 72 + "┘", C.SOFT_PURPLE, C.BOLD))
        answer = input("[y/N] Approve this action? ").strip().lower()
        print()
        return answer in {"y", "yes"}

    def _build_user_message(self, user_text: str) -> str:
        parts: list[str] = []
        if self.session.plan_mode:
            parts.append("[PLAN MODE] Think step-by-step before making any file changes.\n")
        if self.pending_skill:
            parts.append(f"[SKILL CONTEXT]\n{self.pending_skill}\n")
            self.pending_skill = ""
        if self.pending_directive:
            parts.append(self.pending_directive)
            self.pending_directive = ""
            if user_text.strip():
                parts.append(user_text)
            return "\n".join(parts)
        return user_text

    def stream_chat(self, user_text: str) -> str:
        effective = self._build_user_message(user_text)
        payload = {
            "model": self.config.model,
            "mode": self.config.model_mode,
            "modelMode": self.config.model_mode,
            "searchWeb": self.config.search_web,
            "conversationId": self.config.conversation_id,
            "agentMode": self.config.agent_mode,
            "projectPath": os.getcwd(),
            "systemPrompt": load_system_prompt(),
            "stream": True,
            "effort": self.session.effort,
            "messages": self.messages + [{"role": "user", "content": effective}],
        }
        headers = {"Content-Type": "application/json", "X-Geocentric-Client": "cli"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        req = Request(
            self._url("/api/chat"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        raw = ""
        reasoning_buf = ""
        last_status = ""
        reasoning_tokens = 0
        stream_tokens = 0
        usage_payload: Optional[dict[str, Any]] = None
        self._seen_tools.clear()
        self.dash.clear_thinking()
        self.dash.clear_streaming()
        self.dash.token_count = 0
        self.dash.prompt_tokens = 0
        self.dash.completion_tokens = 0
        self.dash.reasoning_tokens = 0
        self.dash.update_thinking(detail="Starting…", reasoning_tokens=0, token_count=0)

        with urlopen(req, timeout=600) as resp:
            content_type = resp.headers.get("Content-Type") or ""
            if "text/event-stream" not in content_type:
                body = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                raw = filter_stream_noise(_extract_delta(body)[0] or str(body.get("reply") or ""))
                stream_tokens += estimate_tokens(raw)
                clean = strip_internal_tags(raw)
                self.dash.finish_assistant(clean)
                self.session.token_usage += stream_tokens
                self._sync_dash()
                return clean

            buffer = ""

            def process_packet(packet: str) -> None:
                nonlocal raw, reasoning_buf, last_status, reasoning_tokens, stream_tokens, usage_payload
                for line in packet.split("\n"):
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        return
                    try:
                        parsed = json.loads(data_str)
                    except Exception:
                        continue
                    content, reasoning = _extract_delta(parsed)
                    content = filter_stream_noise(content)
                    reasoning = filter_stream_noise(reasoning)
                    usage_payload = None
                    if isinstance(parsed, dict):
                        usage_payload = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else None

                    if reasoning:
                        reasoning_buf += reasoning
                        reasoning_tokens += estimate_tokens(reasoning)
                        stream_tokens += estimate_tokens(reasoning)
                        detail = latest_status(raw) or reasoning.strip().splitlines()[-1][:80] or "Reasoning…"
                        self.dash.update_thinking(
                            detail=detail,
                            reasoning_tokens=reasoning_tokens,
                            usage=usage_payload,
                            token_count=stream_tokens,
                        )

                    if content:
                        raw += content
                        stream_tokens += estimate_tokens(content)
                        status = latest_status(raw)
                        if status and status != last_status:
                            last_status = status
                            self.dash.update_thinking(
                                detail=status,
                                reasoning_tokens=reasoning_tokens,
                                usage=usage_payload,
                                token_count=stream_tokens,
                            )
                        elif not reasoning_buf:
                            self.dash.update_thinking(
                                detail=latest_status(raw) or "Generating response…",
                                reasoning_tokens=reasoning_tokens,
                                usage=usage_payload,
                                token_count=stream_tokens,
                            )

                        for action in extract_tool_actions(raw, self._seen_tools):
                            if self._should_prompt_for_tool(action.tool):
                                approved = self._prompt_for_tool_action(action)
                                if not approved:
                                    self.dash.add("status", f"Cancelled {action.tool}")
                                    continue
                            detail = action.detail or action.tool.replace("_", " ")
                            self.dash.update_thinking(
                                detail=f"Running {detail}",
                                reasoning_tokens=reasoning_tokens,
                                token_count=stream_tokens,
                            )
                            self.dash.add("tool", f"Running: {detail}")

                    if usage_payload:
                        self.dash.update_thinking(
                            detail=last_status or "Generating response…",
                            reasoning_tokens=reasoning_tokens,
                            usage=usage_payload,
                            token_count=stream_tokens,
                        )

            while True:
                try:
                    chunk = resp.read(4096)
                except IncompleteRead as exc:
                    if exc.partial:
                        buffer += exc.partial.decode("utf-8", errors="replace")
                    break
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    packet, buffer = buffer.split("\n\n", 1)
                    process_packet(packet)

            if buffer.strip():
                for packet in [part for part in buffer.split("\n\n") if part.strip()]:
                    process_packet(packet)

        self.session.token_usage += stream_tokens
        final = strip_internal_tags(raw)
        if final:
            self.dash.finish_assistant(final)
        elif reasoning_buf.strip():
            self.dash.finish_assistant(reasoning_buf.strip(), dim=True)
        elif last_status:
            self.dash.clear_thinking()
            self.dash.add("status", last_status)
        else:
            self.dash.clear_thinking()
        self._sync_dash()
        return final

    def login(self, email: str, password: str) -> None:
        data = _request_json(
            self._url("/api/auth/login"),
            method="POST",
            payload={"email": email, "password": password},
            timeout=20,
        )
        self.config.token = str(data.get("token") or "")
        self.config.save()

    def handle_slash(self, line: str) -> bool:
        return handle_slash(self, line)

    def _ensure_valid_model(self) -> None:
        try:
            models = self.list_models()
            if not models:
                return
            if self.config.model not in models:
                preferred = next(
                    (m for m in models if "agent" in m.lower() or "thinking" in m.lower()),
                    models[0],
                )
                self.config.model = preferred
                self.session.model = preferred
                self.dash.model = preferred
                self.config.save()
        except Exception:
            pass

    @property
    def ui(self):
        return self.dash

    def _read_input(self) -> Optional[str]:
        try:
            return self._read_input_prompt_toolkit()
        except Exception as exc:
            print(f"Input error: {exc}")
            return self._readline_input()

    def _read_input_prompt_toolkit(self) -> Optional[str]:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style

        history_path = os.path.expanduser("~/.geocentric/cli_history")
        os.makedirs(os.path.dirname(history_path), exist_ok=True)

        style = Style.from_dict({
            "prompt": "#d78700 bold",
            "completion-menu": "bg:#262626 fg:#cccccc",
            "completion-menu.completion": "bg:#262626 fg:#cccccc",
            "completion-menu.completion.current": "bg:#ffffff fg:#000000 bold",
            "completion-menu.meta": "bg:#262626 fg:#888888",
        })

        kb = KeyBindings()

        @kb.add("s-tab")
        def _toggle_auto_accept(event) -> None:
            self._auto_accept = not self._auto_accept
            self.dash.add("status", "AUTO ACCEPT MODE" if self._auto_accept else "Auto accept disabled")

        if self._prompt_session is None:
            self._prompt_session = PromptSession(
                history=FileHistory(history_path),
                completer=SlashOnlyCompleter(self._commands, self._cmd_desc),
                complete_while_typing=True,
                style=style,
                key_bindings=kb,
            )

        self._sync_dash()

        inner = self.dash._inner_width()
        line = "─" * inner
        print(paint(line, C.GRAY))

        text = self._prompt_session.prompt(
            [("class:prompt", "❯ ")],
            bottom_toolbar=lambda: self.dash._footer(auto_accept=self._auto_accept),
        )

        print(paint(line, C.GRAY))
        return text.strip()

    def _readline_input(self) -> Optional[str]:
        try:
            line = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return line

    def repl(self) -> None:
        self._load_resume_context()
        fresh_start = not bool(self._continue_chat) and not self.messages
        self._sync_dash()
        self.dash.enter()
        if self.ping():
            self._ensure_valid_model()
        if not self.ping():
            self.dash.add("error", "Server not reachable — start with ./run.sh or use /connect")
        save_session(self.session)

        try:
            while True:
                try:
                    line = self._read_input()
                except KeyboardInterrupt:
                    print("\n  (interrupted — type /exit to quit)")
                    continue

                if line is None:
                    break
                if not line:
                    continue
                if line == "\u0009":
                    self._auto_accept = not self._auto_accept
                    self.dash.add("status", "AUTO ACCEPT MODE" if self._auto_accept else "Auto accept disabled")
                    continue
                if line.startswith("/"):
                    if line.strip().lower() in {"/exit", "/quit", "/q"}:
                        break
                    self.handle_slash(line)
                    self._sync_dash()
                    continue

                save_checkpoint(self.session)
                try:
                    reply = self.stream_chat(line)
                    if not self.btw_message:
                        self.messages.append({"role": "user", "content": line})
                        self.messages.append({"role": "assistant", "content": reply})
                        self.session.messages = list(self.messages)
                        save_conversation_history(self.config.conversation_id, self.messages)
                    else:
                        self.btw_message = ""
                    save_session(self.session)
                except HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace")
                    self.dash.show_error_panel(f"HTTP {exc.code}", detail[:200])
                except URLError as exc:
                    self.dash.show_error_panel("Connection", str(exc.reason))
                except Exception as exc:
                    self.dash.show_error_panel("Runtime", str(exc))
        finally:
            save_session(self.session)
            self.dash.leave()


def run_interactive_cli(
    *,
    server: Optional[str] = None,
    model: Optional[str] = None,
    mode: str = "thinking",
    token: Optional[str] = None,
    agent: bool = True,
    connect_only: bool = False,
    continue_chat: Optional[str] = None,
    force: bool = False,
) -> None:
    config = CliConfig.load()
    if server:
        config.server = _normalize_server(server)
    if model:
        config.model = model
    if mode:
        config.model_mode = mode
    if token is not None:
        config.token = token
    config.agent_mode = agent
    config.save()

    cli = InteractiveCLI(config, continue_chat=continue_chat, force=force)
    if connect_only and not cli.ping():
        raise SystemExit(f"Could not connect to {config.server}. Is the host server running?")
    cli.repl()
