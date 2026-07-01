"""Modular tool parsing, execution routing, and state tracking for Geocentric.

This module provides a lightweight but production-oriented runtime for XML-style
agent tool tags. It is intentionally split from the server transport so the
same parser can power chat streaming, sandbox execution, and future multi-agent
orchestration.
"""

from __future__ import annotations

import difflib
import html
import json
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


_TOOL_NAMES = {
    "think",
    "plan",
    "final_answer",
    "tool_router",
    "loop_control",
    "error_handler",
    "self_reflect",
    "context_summarize",
    "read_file",
    "write_file",
    "append_file",
    "delete_file",
    "move_file",
    "list_dir",
    "search_files",
    "grep",
    "diff_file",
    "apply_patch",
    "run_shell",
    "run_python",
    "run_node",
    "run_binary",
    "capture_output",
    "kill_process",
    "background_job",
    "web_search",
    "web_open",
    "web_fetch",
    "web_summarize",
    "web_extract_code",
    "docs_lookup",
    "pip_install",
    "npm_install",
    "cargo_install",
    "system_install",
    "dependency_scan",
    "lockfile_update",
    "memory_store",
    "memory_retrieve",
    "project_index",
    "embedding_index",
    "semantic_search",
    "sandbox_exec",
    "permission_check",
    "audit_log",
    "resource_limit",
    "network_toggle",
    "git_status",
    "git_diff",
    "git_commit",
    "git_branch",
    "git_merge",
    "git_revert",
    "code_explain",
    "code_refactor",
    "bug_detect",
    "test_generate",
    "test_run",
    "test_fix_loop",
    "spawn_subagent",
    "agent_message",
    "task_queue",
    "priority_reorder",
    "parallel_execute",
}


@dataclass
class ToolInvocation:
    name: str
    attrs: dict[str, str] = field(default_factory=dict)
    body: str = ""
    raw: str = ""
    start: int = 0


class ToolExecutionState:
    """Tracks plans, statuses, tool invocations, and claim assertions."""

    def __init__(self) -> None:
        self.plans: list[dict[str, Any]] = []
        self.statuses: list[str] = []
        self.tools: list[ToolInvocation] = []
        self.claims: list[str] = []

    def record_status(self, message: str) -> None:
        if message:
            self.statuses.append(message.strip())

    def record_plan(self, plan: Any) -> None:
        if plan is not None:
            self.plans.append(plan if isinstance(plan, dict) else {"value": plan})

    def record_tool(self, tool: ToolInvocation) -> None:
        self.tools.append(tool)

    def record_claim(self, claim: str) -> None:
        if claim:
            self.claims.append(claim.strip())

    def snapshot(self) -> dict[str, Any]:
        return {
            "plans": self.plans,
            "statuses": self.statuses[-8:],
            "tools": [tool.name for tool in self.tools[-8:]],
            "claims": self.claims[-8:],
        }


class ToolRuntime:
    """Parses and routes XML tool invocations to backend handlers."""

    def __init__(self, workspace_dir: str | os.PathLike[str] | None = None, registry: Mapping[str, Callable[[ToolInvocation, ToolExecutionState], Any]] | None = None) -> None:
        self.workspace_dir = Path(workspace_dir or ".").resolve()
        self.registry = dict(registry or self._default_registry())
        self.state = ToolExecutionState()

    def parse(self, text: str) -> list[ToolInvocation]:
        src = text or ""
        invocations: list[ToolInvocation] = []
        for match in re.finditer(r"<(?P<name>[a-zA-Z_][a-zA-Z0-9_-]*)(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=name)>", src, flags=re.IGNORECASE | re.DOTALL):
            name = match.group("name").lower()
            if name not in _TOOL_NAMES:
                continue
            attrs = self._parse_attrs(match.group("attrs"))
            invocation = ToolInvocation(name=name, attrs=attrs, body=match.group("body"), raw=match.group(0), start=match.start())
            invocations.append(invocation)
        for match in re.finditer(r"<(?P<name>[a-zA-Z_][a-zA-Z0-9_-]*)(?P<attrs>[^>]*)/>", src, flags=re.IGNORECASE | re.DOTALL):
            name = match.group("name").lower()
            if name not in _TOOL_NAMES:
                continue
            attrs = self._parse_attrs(match.group("attrs"))
            invocation = ToolInvocation(name=name, attrs=attrs, body="", raw=match.group(0), start=match.start())
            invocations.append(invocation)
        invocations.sort(key=lambda item: item.start)
        return invocations

    def execute(self, text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for invocation in self.parse(text):
            self.state.record_tool(invocation)
            handler = self.registry.get(invocation.name)
            result = handler(invocation, self.state) if handler else self._default_handler(invocation)
            results.append({"tool": invocation.name, "ok": True, "result": result})
        return results

    def _default_handler(self, invocation: ToolInvocation) -> dict[str, Any]:
        return {"status": "queued", "message": f"Tool {invocation.name} registered for execution."}

    def _default_registry(self) -> dict[str, Callable[[ToolInvocation, ToolExecutionState], Any]]:
        def handle_plan(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            plan = []
            for line in (invocation.body or "").splitlines():
                line = line.strip()
                if line:
                    plan.append(line)
            state.record_plan(plan if plan else {"steps": []})
            return {"plan": plan}

        def handle_read_file(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            path = self._resolve_path(invocation.attrs.get("filename") or invocation.attrs.get("path") or "")
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_write_file(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            path = self._resolve_path(invocation.attrs.get("filename") or invocation.attrs.get("path") or "")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(invocation.body or "", encoding="utf-8")
                return {"written": str(path)}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_append_file(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            path = self._resolve_path(invocation.attrs.get("filename") or invocation.attrs.get("path") or "")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(invocation.body or "")
                return {"appended": str(path)}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_delete_file(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            path = self._resolve_path(invocation.attrs.get("filename") or invocation.attrs.get("path") or "")
            try:
                if path.exists():
                    path.unlink()
                return {"deleted": str(path)}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_move_file(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            src = self._resolve_path(invocation.attrs.get("from") or "")
            dst = self._resolve_path(invocation.attrs.get("to") or "")
            try:
                src.rename(dst)
                return {"moved": [str(src), str(dst)]}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_list_dir(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            path = self._resolve_path(invocation.attrs.get("path") or ".")
            try:
                entries = sorted([entry.name for entry in path.iterdir()]) if path.exists() else []
                return {"path": str(path), "entries": entries}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_run_shell(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            command = invocation.attrs.get("command") or (invocation.body or "").strip()
            try:
                proc = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=str(self.workspace_dir), timeout=20)
                return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_run_python(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            code = invocation.attrs.get("code") or invocation.body or ""
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
                    fh.write(code)
                    tmp_path = fh.name
                proc = subprocess.run(["python3", tmp_path], capture_output=True, text=True, cwd=str(self.workspace_dir), timeout=20)
                return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_memory_store(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            key = invocation.attrs.get("key") or ""
            value = invocation.attrs.get("value") or invocation.body or ""
            store_path = self.workspace_dir / ".geocentric" / "memory.json"
            try:
                store_path.parent.mkdir(parents=True, exist_ok=True)
                data = {}
                if store_path.exists():
                    data = json.loads(store_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                data[key] = value
                store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return {"stored": key}
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_memory_retrieve(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            key = invocation.attrs.get("key") or ""
            store_path = self.workspace_dir / ".geocentric" / "memory.json"
            if not store_path.exists():
                return None
            try:
                data = json.loads(store_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                return data.get(key)
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_git_status(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            try:
                proc = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=str(self.workspace_dir), timeout=20)
                return proc.stdout.strip() or "clean"
            except Exception as exc:
                return f"ERROR: {exc}"

        def handle_default(invocation: ToolInvocation, state: ToolExecutionState) -> Any:
            return {"status": "queued", "message": f"Tool {invocation.name} registered for execution."}

        return {
            "think": handle_default,
            "plan": handle_plan,
            "final_answer": handle_default,
            "tool_router": handle_default,
            "loop_control": handle_default,
            "error_handler": handle_default,
            "self_reflect": handle_default,
            "context_summarize": handle_default,
            "read_file": handle_read_file,
            "write_file": handle_write_file,
            "append_file": handle_append_file,
            "delete_file": handle_delete_file,
            "move_file": handle_move_file,
            "list_dir": handle_list_dir,
            "search_files": handle_default,
            "grep": handle_default,
            "diff_file": handle_default,
            "apply_patch": handle_default,
            "run_shell": handle_run_shell,
            "run_python": handle_run_python,
            "run_node": handle_default,
            "run_binary": handle_default,
            "capture_output": handle_default,
            "kill_process": handle_default,
            "background_job": handle_default,
            "web_search": handle_default,
            "web_open": handle_default,
            "web_fetch": handle_default,
            "web_summarize": handle_default,
            "web_extract_code": handle_default,
            "docs_lookup": handle_default,
            "pip_install": handle_default,
            "npm_install": handle_default,
            "cargo_install": handle_default,
            "system_install": handle_default,
            "dependency_scan": handle_default,
            "lockfile_update": handle_default,
            "memory_store": handle_memory_store,
            "memory_retrieve": handle_memory_retrieve,
            "project_index": handle_default,
            "embedding_index": handle_default,
            "semantic_search": handle_default,
            "sandbox_exec": handle_default,
            "permission_check": handle_default,
            "audit_log": handle_default,
            "resource_limit": handle_default,
            "network_toggle": handle_default,
            "git_status": handle_git_status,
            "git_diff": handle_default,
            "git_commit": handle_default,
            "git_branch": handle_default,
            "git_merge": handle_default,
            "git_revert": handle_default,
            "code_explain": handle_default,
            "code_refactor": handle_default,
            "bug_detect": handle_default,
            "test_generate": handle_default,
            "test_run": handle_default,
            "test_fix_loop": handle_default,
            "spawn_subagent": handle_default,
            "agent_message": handle_default,
            "task_queue": handle_default,
            "priority_reorder": handle_default,
            "parallel_execute": handle_default,
        }

    def _resolve_path(self, raw_path: str) -> Path:
        if not raw_path:
            return self.workspace_dir
        path = Path(raw_path)
        if not path.is_absolute():
            path = (self.workspace_dir / path).resolve()
        return path

    def _parse_attrs(self, attrs: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for match in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_-]*)=(?:"([^"]*)"|\'([^\']*)\')', attrs):
            parsed[match.group(1)] = html.unescape(match.group(2) or match.group(3) or "")
        return parsed


_ACTION_CLAIM_RE = re.compile(
    r"\b(i|we|the agent|the system)\s+(updated|wrote|created|deleted|moved|installed|ran|executed|searched|checked|uploaded|edited|replaced|patched|committed|merged|reverted|opened|browsed|captured|analyzed|refactored|fixed|tested|verified|saved|indexed|summarized|deployed)\b",
    re.IGNORECASE,
)


def classify_status_theme(status_text: str) -> str:
    text = (status_text or "").lower()
    if any(word in text for word in ("blurpling", "interrogating", "scoping", "gathering", "inspect", "scanning")):
        return "gathering"
    if any(word in text for word in ("massaging", "pondering", "simulating", "thinking", "reasoning", "reflect")):
        return "thinking"
    if any(word in text for word in ("weaving", "firing", "deploying", "running", "executing", "install", "writing", "editing")):
        return "executing"
    return "neutral"


def render_status_banner(status_text: str, *, theme: str | None = None) -> str:
    theme = theme or classify_status_theme(status_text)
    icon = {
        "gathering": "◉",
        "thinking": "◆",
        "executing": "⚙",
        "neutral": "•",
    }.get(theme, "•")
    return f"{icon} {status_text.strip()}"


def enforce_tool_claim_guard(claim_text: str, tool_context: str = "") -> bool:
    """Return True when a claim is supported by an explicit tool invocation."""
    text = (claim_text or "").strip()
    if not text:
        return True
    if _ACTION_CLAIM_RE.search(text):
        tool_block = bool(re.search(r"<(?:write_file|append_file|delete_file|move_file|read_file|run_shell|run_python|run_node|run_binary|web_search|pip_install|npm_install|cargo_install|system_install|git_commit|git_merge|git_revert|agent_message|spawn_subagent|parallel_execute|apply_patch|edit_file|run_command|run_file|agent_terminal|browse_url|list_directory|make_directory|copy_file|download_url|install_package|http_request|view_project_tree|update_roadmap)[^>]*", tool_context or "", flags=re.IGNORECASE))
        if not tool_block:
            return False
    return True
