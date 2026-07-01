"""Shell/process execution tools."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from typing import Any

from . import ToolContext, ToolSpec

_DEFAULT_TIMEOUT = 30


def _normalize_python_command(command: str) -> str:
    return re.sub(r"^python(\s|$)", shlex.quote(sys.executable) + r"\1", command.strip(), count=1)


def run_command(args: dict[str, Any], ctx: ToolContext) -> str:
    cmd = str(args.get("command", "")).strip()
    timeout = int(args.get("timeout", _DEFAULT_TIMEOUT))
    if not cmd:
        return "[RUN COMMAND ERROR] No command provided."
    if ctx.on_status:
        ctx.on_status(f"Running command: {cmd.splitlines()[0]}")

    executable_cmd = _normalize_python_command(cmd)
    try:
        result = subprocess.run(
            executable_cmd,
            shell=True,
            cwd=str(ctx.workspace_dir.resolve()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"[RUN COMMAND ERROR] Command timed out after {timeout}s: {cmd}"

    output = result.stdout or ""
    if result.stderr:
        output += "\n--- STDERR ---\n" + result.stderr
    if result.returncode != 0:
        output += f"\nProcess exited with non-zero exit code: {result.returncode}"
    return f"[RUN COMMAND RESULT] Output of `{cmd}`:\n{output if output.strip() else 'Command completed successfully with empty output.'}"


SPECS = [
    ToolSpec(
        name="run_command",
        description="Run a shell command in the workspace directory and capture its output.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds before the command is killed (default 30)"},
            },
            "required": ["command"],
        },
        handler=run_command,
        requires_approval=True,
        legacy_tag_aliases=("run_command", "run_shell"),
    ),
]
