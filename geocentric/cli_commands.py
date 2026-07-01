"""Geocentric Code CLI — slash command registry and handlers."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.error import HTTPError

from geocentric.cli_session import (
    compact_messages,
    list_checkpoints,
    list_sessions,
    load_session,
    restore_checkpoint,
    rewind_messages,
    save_checkpoint,
    save_session,
)
from geocentric.cli_ui import format_error, format_info, format_success, print_help_section

if TYPE_CHECKING:
    from geocentric.interactive_cli import InteractiveCLI


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    category: str
    aliases: tuple[str, ...] = ()


def _all_commands() -> list[SlashCommand]:
    return [
        # Session
        SlashCommand("/help", "List commands", "Session", ("/?",)),
        SlashCommand("/clear", "Clear chat context", "Session", ("/reset",)),
        SlashCommand("/new", "Start fresh conversation", "Session"),
        SlashCommand("/compact", "Summarize and compress history", "Session"),
        SlashCommand("/resume", "Reopen a saved session", "Session", ("/continue",)),
        SlashCommand("/rename", "Rename current session", "Session"),
        SlashCommand("/context", "Show token and context usage", "Session"),
        SlashCommand("/rewind", "Roll back conversation turns", "Session"),
        SlashCommand("/exit", "Close CLI", "Session", ("/quit", "/q")),
        # Model
        SlashCommand("/model", "Switch model", "Model"),
        SlashCommand("/models", "List models on server", "Model"),
        SlashCommand("/effort", "Reasoning intensity (low|medium|high|max)", "Model"),
        SlashCommand("/mode", "Switch thinking|instant mode", "Model"),
        SlashCommand("/plan", "Toggle planning mode before edits", "Model"),
        # Project
        SlashCommand("/init", "Generate GEOCENTRIC.md from repo scan", "Project"),
        SlashCommand("/memory", "Edit project memory file", "Project"),
        SlashCommand("/config", "Show session settings", "Project", ("/settings",)),
        # Workflow
        SlashCommand("/diff", "Show git diff summary", "Workflow"),
        SlashCommand("/review", "Code review pass", "Workflow"),
        SlashCommand("/export", "Export conversation to JSON", "Workflow"),
        # Local
        SlashCommand("/status", "Session, model, and server info", "Local"),
        SlashCommand("/doctor", "Diagnose install and environment", "Local"),
        SlashCommand("/debug", "Runtime debugging info", "Local"),
        SlashCommand("/agent", "Toggle workspace agent mode", "Local"),
        SlashCommand("/search", "Toggle web search", "Local"),
        SlashCommand("/server", "Show or set server URL", "Local"),
        SlashCommand("/connect", "Connect to a Geocentric host", "Local"),
        SlashCommand("/skills", "List installed skills", "Local"),
        SlashCommand("/agents", "Toggle coordinator mode for parallel sub-tasks", "Workflow"),
        # Remote shell (WiFi access)
        SlashCommand("/ls", "List remote directory", "Remote"),
        SlashCommand("/cd", "Change remote directory", "Remote"),
        SlashCommand("/pwd", "Print remote working directory", "Remote"),
        SlashCommand("/mkdir", "Create remote directory", "Remote"),
        SlashCommand("/shell", "Execute remote shell command", "Remote"),
    ]


COMMAND_REGISTRY = _all_commands()
COMMAND_NAMES = sorted({c.name for c in COMMAND_REGISTRY} | {a for c in COMMAND_REGISTRY for a in c.aliases})
COMMAND_MAP: dict[str, SlashCommand] = {}
for cmd in COMMAND_REGISTRY:
    COMMAND_MAP[cmd.name] = cmd
    for alias in cmd.aliases:
        COMMAND_MAP[alias] = cmd


def discover_skills() -> dict[str, Path]:
    roots = [
        Path.cwd() / ".claude" / "skills",
        Path.cwd() / "skills",
        Path(os.path.expanduser("~/.geocentric/skills")),
    ]
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for skill_dir in root.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                found[f"/{skill_dir.name}"] = skill_md
    return found


def all_command_names() -> list[str]:
    return sorted(set(COMMAND_NAMES) | set(discover_skills().keys()))


def print_full_help() -> None:
    print("\n  Geocentric Code — commands\n")
    by_cat: dict[str, list[SlashCommand]] = {}
    for cmd in COMMAND_REGISTRY:
        by_cat.setdefault(cmd.category, []).append(cmd)
    for category, cmds in by_cat.items():
        print_help_section(category, [(c.name, c.description) for c in cmds])
    skills = discover_skills()
    if skills:
        print_help_section("Skills", [(name, path.parent.name) for name, path in sorted(skills.items())])
    print(format_info("Edit SYSTEMPROMPT.md in the project root to customize agent behavior"))
    print(format_info("Config: ~/.geocentric/cli.json"))
    print()


def handle_slash(cli: "InteractiveCLI", line: str) -> bool:
    parts = line.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]
    arg_str = " ".join(args)

    skills = discover_skills()
    if cmd in skills:
        cli.pending_skill = skills[cmd].read_text(encoding="utf-8")
        print(format_success(f"Skill {cmd} loaded — describe your task on the next line."))
        return True

    if cmd not in COMMAND_MAP:
        matches = [c for c in all_command_names() if c.lower().startswith(cmd) or cmd[1:] in c[1:]]
        print(format_error(f"Unknown command: {cmd}"))
        if matches:
            print(format_info("Did you mean: " + ", ".join(matches[:6])))
        else:
            print(format_info("Type /help for available commands."))
        return True

    if cmd in {"/help", "/?"}:
        print_full_help()
        return True

    if cmd in {"/exit", "/quit", "/q"}:
        save_session(cli.session)
        sys.exit(0)

    if cmd in {"/clear", "/reset"}:
        cli.messages.clear()
        cli.session.messages.clear()
        cli.session.conversation_id = uuid.uuid4().hex
        save_checkpoint(cli.session)
        save_session(cli.session)
        print(format_success("Conversation cleared."))
        return True

    if cmd == "/new":
        save_checkpoint(cli.session)
        cli.session.conversation_id = uuid.uuid4().hex
        cli.messages.clear()
        cli.session.messages.clear()
        save_session(cli.session)
        print(format_success("Started new conversation."))
        return True

    if cmd == "/compact":
        instructions = arg_str.strip()
        compacted, summary = compact_messages(cli.messages, instructions)
        cli.messages = compacted
        cli.session.messages = compacted
        cli.session.summary = summary
        save_session(cli.session)
        print(format_success(f"Compacted history. {summary}"))
        return True

    if cmd in {"/resume", "/continue"}:
        sid = args[0] if args else ""
        if not sid:
            sessions = list_sessions()
            if not sessions:
                print(format_info("No saved sessions yet."))
                return True
            print(format_info("Saved sessions:"))
            for s in sessions[:10]:
                print(f"    {s.id}  {s.name}  ({len(s.messages)} msgs)")
            return True
        loaded = load_session(sid)
        if not loaded:
            print(format_error(f"Session not found: {sid}"))
            return True
        cli.session = loaded
        cli.messages = list(loaded.messages)
        cli.config.conversation_id = loaded.conversation_id
        cli.config.model = loaded.model
        cli.config.model_mode = loaded.model_mode
        cli.config.save()
        cli.dash.model = loaded.model
        cli.dash.effort = loaded.effort
        print(format_success(f"Resumed session '{loaded.name}' ({loaded.id})"))
        return True

    if cmd == "/rename":
        name = arg_str.strip() or input("Session name: ").strip()
        if name:
            cli.session.name = name
            save_session(cli.session)
            print(format_success(f"Session renamed to '{name}'"))
        return True

    if cmd == "/context":
        msg_tokens = sum(len(m.get("content", "")) // 4 for m in cli.messages)
        print(format_info(f"Messages: {len(cli.messages)}  (~{msg_tokens:,} tokens)"))
        print(format_info(f"Session tokens: {cli.session.token_usage:,}"))
        print(format_info(f"Conversation ID: {cli.config.conversation_id}"))
        print(format_info(f"Effort: {cli.session.effort}  Plan mode: {cli.session.plan_mode}"))
        return True

    if cmd == "/rewind":
        if args and not args[0].isdigit():
            cp = restore_checkpoint(cli.session.id, args[0])
            if cp:
                cli.messages = cp.get("messages", [])
                cli.session.messages = list(cli.messages)
                cli.config.conversation_id = cp.get("conversation_id", cli.config.conversation_id)
                save_session(cli.session)
                print(format_success(f"Restored checkpoint {args[0]}"))
            else:
                print(format_error("Checkpoint not found."))
            return True
        turns = int(args[0]) if args and args[0].isdigit() else 1
        checkpoints = list_checkpoints(cli.session.id)
        cli.messages = rewind_messages(cli.messages, turns)
        cli.session.messages = list(cli.messages)
        save_session(cli.session)
        print(format_success(f"Rewound {turns} turn(s). Checkpoints: {len(checkpoints)}"))
        return True

    if cmd == "/model":
        if args:
            cli.config.model = args[0]
            cli.session.model = args[0]
            cli.dash.model = args[0]
            cli.config.save()
            save_session(cli.session)
            print(format_success(f"Model: {cli.config.model}"))
        else:
            try:
                models = cli.list_models()
                print(format_info("Available models:"))
                for name in models:
                    mark = " *" if name == cli.config.model else ""
                    print(f"    {name}{mark}")
            except Exception as exc:
                print(format_error(str(exc)))
        return True

    if cmd == "/models":
        try:
            for name in cli.list_models():
                mark = " *" if name == cli.config.model else ""
                print(f"    {name}{mark}")
        except Exception as exc:
            print(format_error(str(exc)))
        return True

    if cmd == "/effort":
        levels = {"low", "medium", "high", "max"}
        if args and args[0].lower() in levels:
            cli.session.effort = args[0].lower()
            cli.dash.set_effort(cli.session.effort)
            save_session(cli.session)
        print(format_info(f"Effort: {cli.session.effort}  (low · medium · high · max)"))
        return True

    if cmd == "/plan":
        cli.session.plan_mode = not cli.session.plan_mode
        save_session(cli.session)
        state = "on" if cli.session.plan_mode else "off"
        print(format_success(f"Planning mode {state}."))
        return True

    if cmd == "/mode":
        if args and args[0] in {"thinking", "instant"}:
            cli.config.model_mode = args[0]
            cli.session.model_mode = args[0]
            cli.dash.mode = args[0]
            cli.config.save()
            save_session(cli.session)
        print(format_info(f"Mode: {cli.config.model_mode}"))
        return True

    if cmd == "/init":
        geocentric_path = Path.cwd() / "GEOCENTRIC.md"
        if geocentric_path.exists():
            print(format_info("GEOCENTRIC.md already exists."))
        else:
            geocentric_path.write_text(_generate_geocentric_md(Path.cwd()), encoding="utf-8")
            print(format_success("Created GEOCENTRIC.md from repo scan."))
        return True

    if cmd == "/memory":
        mem = Path.cwd() / "memory.md"
        if not mem.exists():
            templates = Path.cwd() / "templates" / "memory.md"
            if templates.exists():
                shutil.copy(templates, mem)
            else:
                mem.write_text("# Project Memory\n\n", encoding="utf-8")
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(mem)], check=False)
        return True

    if cmd in {"/config", "/settings"}:
        print(format_info(f"Config: {os.path.expanduser('~/.geocentric/cli.json')}"))
        print(json.dumps({
            "server": cli.config.server,
            "model": cli.config.model,
            "model_mode": cli.config.model_mode,
            "agent_mode": cli.config.agent_mode,
            "search_web": cli.config.search_web,
            "effort": cli.session.effort,
        }, indent=2))
        return True

    if cmd == "/diff":
        try:
            result = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True, timeout=10)
            print(result.stdout or result.stderr or "(no git diff)")
        except Exception as exc:
            print(format_error(str(exc)))
        return True

    if cmd == "/review":
        cli.pending_directive = "Run a thorough code review on recent changes. Focus on bugs, edge cases, and clarity."
        print(format_success("Review mode — describe scope or press Enter to review git diff."))
        return True

    if cmd == "/export":
        out = Path.cwd() / f"geocentric-export-{cli.session.id}.json"
        out.write_text(json.dumps({"session": cli.session.to_dict(), "messages": cli.messages}, indent=2), encoding="utf-8")
        print(format_success(f"Exported to {out}"))
        return True

    if cmd == "/status":
        print(format_info(f"Server:   {cli.config.server}"))
        print(format_info(f"Model:    {cli.config.model}"))
        print(format_info(f"Mode:     {cli.config.model_mode}"))
        print(format_info(f"Effort:   {cli.session.effort}"))
        print(format_info(f"Agent:    {cli.config.agent_mode}"))
        print(format_info(f"Search:   {cli.config.search_web}"))
        print(format_info(f"Session:  {cli.session.name} ({cli.session.id})"))
        print(format_info(f"CWD:      {Path.cwd()}"))
        print(format_info(f"Online:   {'yes' if cli.ping() else 'no'}"))
        return True

    if cmd == "/doctor":
        _run_doctor(cli)
        return True

    if cmd == "/debug":
        print(format_info(f"Python: {sys.version.split()[0]}  Platform: {platform.platform()}"))
        print(format_info(f"Server: {cli.config.server}  Online: {cli.ping()}"))
        print(format_info(f"Session: {cli.session.id}  Messages: {len(cli.messages)}"))
        print(format_info(f"CWD: {Path.cwd()}"))
        return True

    if cmd == "/agent":
        if args:
            cli.config.agent_mode = args[0].lower() in {"1", "true", "on", "yes"}
        else:
            cli.config.agent_mode = not cli.config.agent_mode
        cli.config.save()
        print(format_info(f"Agent mode: {'on' if cli.config.agent_mode else 'off'}"))
        return True

    if cmd == "/search":
        if args:
            cli.config.search_web = args[0].lower() in {"1", "true", "on", "yes"}
            cli.config.save()
        print(format_info(f"Web search: {'on' if cli.config.search_web else 'off'}"))
        return True

    if cmd == "/server":
        if args:
            cli.config.server = cli._normalize_server(args[0])
            cli.config.save()
            cli.dash.server = cli.config.server
        print(format_info(f"Server: {cli.config.server}"))
        print(format_info(f"Connection: {'OK' if cli.ping() else 'FAILED'}"))
        return True

    if cmd == "/connect":
        host = args[0] if args else input("Server URL (e.g. 192.168.1.10:8000): ").strip()
        cli.config.server = cli._normalize_server(host)
        cli.config.save()
        cli.dash.server = cli.config.server
        ok = cli.ping()
        print(format_success(f"Connected to {cli.config.server}") if ok else format_error(f"Could not reach {cli.config.server}"))
        return True

    if cmd == "/agents":
        cli.session.auto_mode = not cli.session.auto_mode
        save_session(cli.session)
        print(format_success(f"Coordinator mode {'on' if cli.session.auto_mode else 'off'}"))
        return True

    if cmd == "/skills":
        found = discover_skills()
        if not found:
            print(format_info("No skills in .claude/skills/, skills/, or ~/.geocentric/skills/"))
        else:
            for name, path in sorted(found.items()):
                print(f"    {name}  →  {path}")
        return True

    if cmd == "/ls":
        path = arg_str.strip() or "."
        try:
            import json as json_module
            from urllib.request import Request, urlopen
            payload = {"path": path}
            req = Request(
                cli._url("/api/shell/ls"),
                data=json_module.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                result = json_module.loads(resp.read().decode("utf-8"))
            print(format_info(f"Directory: {result.get('path', path)}"))
            for entry in result.get("entries", []):
                mark = "📁" if entry.get("is_dir") else "📄"
                size_str = f" ({entry.get('size')} bytes)" if entry.get("size") > 0 else ""
                print(f"  {mark} {entry.get('name')}{size_str}")
        except Exception as exc:
            print(format_error(f"Cannot list directory: {exc}"))
        return True

    if cmd == "/cd":
        path = arg_str.strip() or "."
        try:
            import json as json_module
            from urllib.request import Request, urlopen
            payload = {"path": path}
            req = Request(
                cli._url("/api/shell/cd"),
                data=json_module.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                result = json_module.loads(resp.read().decode("utf-8"))
            print(format_success(f"Changed to: {result.get('cwd', path)}"))
        except Exception as exc:
            print(format_error(f"Cannot change directory: {exc}"))
        return True

    if cmd == "/pwd":
        try:
            import json as json_module
            from urllib.request import Request, urlopen
            req = Request(
                cli._url("/api/shell/pwd"),
                data=json_module.dumps({}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                result = json_module.loads(resp.read().decode("utf-8"))
            print(format_info(f"Remote directory: {result.get('cwd')}"))
        except Exception as exc:
            print(format_error(f"Cannot get directory: {exc}"))
        return True

    if cmd == "/mkdir":
        path = arg_str.strip()
        if not path:
            print(format_error("Please provide a directory path"))
            return True
        try:
            import json as json_module
            from urllib.request import Request, urlopen
            payload = {"path": path}
            req = Request(
                cli._url("/api/shell/mkdir"),
                data=json_module.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                result = json_module.loads(resp.read().decode("utf-8"))
            print(format_success(f"Created directory: {result.get('created')}"))
        except Exception as exc:
            print(format_error(f"Cannot create directory: {exc}"))
        return True

    if cmd == "/shell":
        shell_cmd = arg_str.strip()
        if not shell_cmd:
            print(format_error("Please provide a shell command"))
            return True
        try:
            import json as json_module
            from urllib.request import Request, urlopen
            payload = {"command": shell_cmd}
            req = Request(
                cli._url("/api/shell/execute"),
                data=json_module.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                result = json_module.loads(resp.read().decode("utf-8"))
            if result.get("stdout"):
                print(result.get("stdout"))
            if result.get("stderr"):
                print(format_error(result.get("stderr")))
            if result.get("exit_code") != 0:
                print(format_error(f"Exit code: {result.get('exit_code')}"))
        except Exception as exc:
            print(format_error(f"Cannot execute command: {exc}"))
        return True

    return True


def _run_doctor(cli: "InteractiveCLI") -> None:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python 3.9+", sys.version_info >= (3, 9), sys.version.split()[0]))
    checks.append(("Server reachable", cli.ping(), cli.config.server))
    venv = Path.cwd() / ".venv" / "bin" / "python"
    checks.append(("Virtual env", venv.exists(), str(venv)))
    try:
        import torch  # noqa: F401
        checks.append(("PyTorch", True, "installed"))
    except ImportError:
        checks.append(("PyTorch", False, "missing"))
    try:
        import prompt_toolkit  # noqa: F401
        checks.append(("prompt_toolkit", True, "installed"))
    except ImportError:
        checks.append(("prompt_toolkit", False, "pip install prompt_toolkit"))
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        checks.append(("Ollama", result.returncode == 0, "running" if result.returncode == 0 else "not found"))
    except Exception:
        checks.append(("Ollama", False, "not found"))
    for name, ok, detail in checks:
        mark = format_success(name) if ok else format_error(name)
        print(f"  {mark}  {detail}")


def _generate_geocentric_md(cwd: Path) -> str:
    lines = ["# GEOCENTRIC.md", "", "Project context for Geocentric Code.", ""]
    lines.append("## Structure")
    for item in sorted(cwd.iterdir())[:30]:
        if item.name.startswith(".") and item.name not in {".github"}:
            continue
        kind = "dir" if item.is_dir() else "file"
        lines.append(f"- `{item.name}` ({kind})")
    lines.extend(["", "## Conventions", "- Match existing code style", "- Run tests before committing", ""])
    skills = discover_skills()
    if skills:
        lines.append("## Skills")
        for name in sorted(skills):
            lines.append(f"- `{name}`")
        lines.append("")
    return "\n".join(lines)
