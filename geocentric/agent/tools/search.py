"""Repository text search (grep).

Previously advertised in the system prompt but never implemented anywhere in
the codebase (confirmed: zero `grep`/`search_files` handlers existed in
server.py's process_sandbox_tags). This closes that gap for M1; a real
indexed/semantic search is M2 scope.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from . import ToolContext, ToolSpec

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".DS_Store"}
_MAX_MATCHES = 200


def _grep_with_ripgrep(pattern: str, workspace_dir, glob: str | None) -> str | None:
    if not shutil.which("rg"):
        return None
    cmd = ["rg", "--line-number", "--no-heading", "--max-count", "20", "--color", "never"]
    if glob:
        cmd += ["--glob", glob]
    cmd += [pattern, "."]
    try:
        result = subprocess.run(cmd, cwd=str(workspace_dir), capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if result.returncode not in (0, 1):
        return None
    lines = result.stdout.splitlines()[:_MAX_MATCHES]
    return "\n".join(lines)


def _grep_with_python(pattern: str, workspace_dir, glob: str | None) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"[GREP ERROR] Invalid regex: {exc}"
    matches: list[str] = []
    for path in workspace_dir.rglob(glob or "*"):
        if len(matches) >= _MAX_MATCHES:
            break
        if path.is_dir() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(workspace_dir)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{rel}:{lineno}:{line.strip()[:200]}")
                if len(matches) >= _MAX_MATCHES:
                    break
    return "\n".join(matches)


def grep(args: dict[str, Any], ctx: ToolContext) -> str:
    pattern = str(args.get("pattern", "")).strip()
    glob = args.get("glob")
    if not pattern:
        return "[GREP ERROR] No pattern provided."
    if ctx.on_status:
        ctx.on_status(f"Searching for: {pattern}")

    output = _grep_with_ripgrep(pattern, ctx.workspace_dir, glob)
    if output is None:
        output = _grep_with_python(pattern, ctx.workspace_dir, glob)
    if not output:
        return f"[GREP RESULT] No matches for '{pattern}'."
    return f"[GREP RESULT] Matches for '{pattern}':\n{output}"


SPECS = [
    ToolSpec(
        name="grep",
        description="Search file contents in the workspace for a regular expression pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for"},
                "glob": {"type": "string", "description": "Optional filename glob to restrict the search, e.g. '*.py'"},
            },
            "required": ["pattern"],
        },
        handler=grep,
        legacy_tag_aliases=("grep", "search_files"),
    ),
]
