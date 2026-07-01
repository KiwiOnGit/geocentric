"""Git tools: status, diff, commit, branch.

These were advertised (`git_commit`) or stubbed as placeholders in the old,
never-instantiated tool_runtime.py `ToolRuntime` registry; implemented for
real here.
"""

from __future__ import annotations

import subprocess
from typing import Any

from . import ToolContext, ToolSpec


def _run_git(args: list[str], ctx: ToolContext, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(ctx.workspace_dir.resolve()),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def git_status(args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.on_status:
        ctx.on_status("Checking git status")
    result = _run_git(["status", "--short", "--branch"], ctx)
    if result.returncode != 0:
        return f"[GIT STATUS ERROR] {result.stderr.strip()}"
    return f"[GIT STATUS RESULT]\n{result.stdout.strip() or '(clean working tree)'}"


def git_diff(args: dict[str, Any], ctx: ToolContext) -> str:
    path = args.get("path")
    if ctx.on_status:
        ctx.on_status("Computing git diff")
    cmd = ["diff"]
    if path:
        cmd.append(str(path))
    result = _run_git(cmd, ctx)
    if result.returncode != 0:
        return f"[GIT DIFF ERROR] {result.stderr.strip()}"
    diff_text = result.stdout
    if len(diff_text) > 20_000:
        diff_text = diff_text[:20_000] + "\n... (diff truncated)"
    return f"[GIT DIFF RESULT]\n{diff_text or '(no changes)'}"


def git_commit(args: dict[str, Any], ctx: ToolContext) -> str:
    message = str(args.get("message", "")).strip()
    if not message:
        return "[GIT COMMIT ERROR] No commit message provided."
    if ctx.on_status:
        ctx.on_status("Creating git commit")
    add_result = _run_git(["add", "-A"], ctx)
    if add_result.returncode != 0:
        return f"[GIT COMMIT ERROR] git add failed: {add_result.stderr.strip()}"
    commit_result = _run_git(["commit", "-m", message], ctx)
    if commit_result.returncode != 0:
        return f"[GIT COMMIT ERROR] {commit_result.stdout.strip()}{commit_result.stderr.strip()}"
    return f"[GIT COMMIT SUCCESS] {commit_result.stdout.strip()}"


def git_branch(args: dict[str, Any], ctx: ToolContext) -> str:
    if ctx.on_status:
        ctx.on_status("Listing git branches")
    result = _run_git(["branch", "--list"], ctx)
    if result.returncode != 0:
        return f"[GIT BRANCH ERROR] {result.stderr.strip()}"
    return f"[GIT BRANCH RESULT]\n{result.stdout.strip()}"


SPECS = [
    ToolSpec(
        name="git_status",
        description="Show the current git working tree status.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=git_status,
        legacy_tag_aliases=("git_status",),
    ),
    ToolSpec(
        name="git_diff",
        description="Show the current uncommitted git diff, optionally scoped to one path.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
        handler=git_diff,
        legacy_tag_aliases=("git_diff", "diff_file"),
    ),
    ToolSpec(
        name="git_commit",
        description="Stage all changes and create a git commit with the given message.",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        handler=git_commit,
        requires_approval=True,
        legacy_tag_aliases=("git_commit",),
    ),
    ToolSpec(
        name="git_branch",
        description="List git branches in the repository.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=git_branch,
        legacy_tag_aliases=("git_branch",),
    ),
]
