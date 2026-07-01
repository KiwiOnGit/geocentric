"""Filesystem tools: read/write/edit/delete/move/copy/list/stat/tree.

Handler logic mirrors geocentric/server.py's process_sandbox_tags file
handlers (same sandbox-escape check, same result-message conventions) so
behavior is familiar, but is implemented fresh here rather than imported --
see workspace.py for why.
"""

from __future__ import annotations

import shutil
import time
from typing import Any

from . import ToolContext, ToolSpec
from ..workspace import resolve_in_workspace, safe_text_snapshot

_SKIP_NAMES = {".git", "__pycache__", ".venv", "venv", "node_modules", ".DS_Store"}


def _status(ctx: ToolContext, message: str) -> None:
    if ctx.on_status:
        ctx.on_status(message)


def read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    _status(ctx, f"Reading file: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    if not target.exists() or not target.is_file():
        return f"[READ FILE ERROR] File '{rel}' does not exist or is a directory."
    content = target.read_text(encoding="utf-8", errors="ignore")
    return f"[READ FILE SUCCESS] Content of '{rel}':\n```\n{content}\n```"


def write_file(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    content = args.get("content", "")
    _status(ctx, f"Writing file: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    old_text = safe_text_snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"[WRITE FILE SUCCESS] Wrote/created file '{rel}' ({len(content)} characters)."


def edit_file(args: dict[str, Any], ctx: ToolContext) -> str:
    """Structured line-range replacement: replace lines [start, end] (1-indexed,
    inclusive) with `content`. Simpler and less ambiguous than the legacy
    insert/delete/replace-per-line tag soup, while remaining easy for a model
    to emit as native tool-call JSON arguments."""
    rel = str(args.get("path", "")).strip()
    start = int(args.get("start_line", 1))
    end = int(args.get("end_line", start))
    content = args.get("content", "")
    _status(ctx, f"Editing file: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    if not target.exists() or not target.is_file():
        return f"[EDIT FILE ERROR] File '{rel}' does not exist."
    old_text = target.read_text(encoding="utf-8", errors="ignore")
    lines = old_text.splitlines()
    start_idx = max(0, start - 1)
    end_idx = min(len(lines), end)
    new_lines = lines[:start_idx] + content.splitlines() + lines[end_idx:]
    target.write_text("\n".join(new_lines), encoding="utf-8")
    return f"[EDIT FILE SUCCESS] Replaced lines {start}-{end} in '{rel}'."


def delete_file(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    _status(ctx, f"Deleting file: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    if not target.exists():
        return f"[DELETE FILE ERROR] Path '{rel}' does not exist."
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return f"[DELETE FILE SUCCESS] Deleted '{rel}'."


def move_file(args: dict[str, Any], ctx: ToolContext) -> str:
    src = str(args.get("source", "")).strip()
    dst = str(args.get("destination", "")).strip()
    _status(ctx, f"Moving {src} to {dst}")
    source = resolve_in_workspace(ctx.workspace_dir, src, ctx.extra_roots)
    target = resolve_in_workspace(ctx.workspace_dir, dst, ctx.extra_roots)
    if not source.exists():
        return f"[MOVE FILE ERROR] Source path does not exist: {src}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return f"[MOVE FILE SUCCESS] Moved '{src}' to '{dst}'."


def copy_file(args: dict[str, Any], ctx: ToolContext) -> str:
    src = str(args.get("source", "")).strip()
    dst = str(args.get("destination", "")).strip()
    _status(ctx, f"Copying {src} to {dst}")
    source = resolve_in_workspace(ctx.workspace_dir, src, ctx.extra_roots)
    target = resolve_in_workspace(ctx.workspace_dir, dst, ctx.extra_roots)
    if not source.exists() or not source.is_file():
        return f"[COPY FILE ERROR] Source file does not exist: {src}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return f"[COPY FILE SUCCESS] Copied '{src}' to '{dst}'."


def make_directory(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    _status(ctx, f"Creating directory: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    target.mkdir(parents=True, exist_ok=True)
    return f"[MAKE DIRECTORY SUCCESS] Created directory '{rel}'."


def list_directory(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", ".")).strip() or "."
    max_entries = int(args.get("max_entries", 120))
    _status(ctx, f"Listing directory: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    if not target.exists():
        return f"[LIST DIRECTORY ERROR] Path does not exist: {rel}"
    if not target.is_dir():
        return f"[LIST DIRECTORY ERROR] Path is not a directory: {rel}"
    children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    rows = []
    for child in children[:max_entries]:
        kind = "dir" if child.is_dir() else "file"
        size = child.stat().st_size if child.is_file() else 0
        rows.append(f"- {kind}: {child.name}{'/' if child.is_dir() else ''} ({size} bytes)")
    if len(children) > max_entries:
        rows.append(f"... {len(children) - max_entries} more entries")
    return f"[LIST DIRECTORY RESULT] {rel}\n" + ("\n".join(rows) if rows else "(empty)")


def stat_path(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    _status(ctx, f"Inspecting path metadata: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel, ctx.extra_roots)
    if not target.exists():
        return f"[STAT PATH ERROR] Path does not exist: {rel}"
    st = target.stat()
    return (
        f"[STAT PATH RESULT] {rel}\n"
        f"Type: {'directory' if target.is_dir() else 'file'}\n"
        f"Size: {st.st_size} bytes\n"
        f"Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}"
    )


def view_project_tree(args: dict[str, Any], ctx: ToolContext) -> str:
    max_depth = int(args.get("max_depth", 5))
    max_entries = int(args.get("max_entries", 300))
    _status(ctx, "Inspecting project folder layout")

    lines: list[str] = [f"{ctx.workspace_dir.name}/"]
    seen = 0

    def fmt_size(path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "?"
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"

    def walk(path, prefix: str = "", depth: int = 0) -> None:
        nonlocal seen
        if seen >= max_entries:
            return
        try:
            children = [c for c in path.iterdir() if c.name not in _SKIP_NAMES and not c.name.startswith(".")]
        except OSError as exc:
            lines.append(f"{prefix}[error reading directory: {exc}]")
            return
        children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        for index, child in enumerate(children):
            if seen >= max_entries:
                lines.append(f"{prefix}... ({max_entries} entry limit reached)")
                return
            connector = "`-- " if index == len(children) - 1 else "|-- "
            suffix = "/" if child.is_dir() else f" ({fmt_size(child)})"
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            seen += 1
            if child.is_dir() and depth + 1 < max_depth:
                extension = "    " if index == len(children) - 1 else "|   "
                walk(child, prefix + extension, depth + 1)

    walk(ctx.workspace_dir)
    return "[PROJECT TREE]\n" + "\n".join(lines)


SPECS = [
    ToolSpec(
        name="read_file",
        description="Read the full text content of a file in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=read_file,
        legacy_tag_aliases=("read_file",),
    ),
    ToolSpec(
        name="write_file",
        description="Create or overwrite a file in the workspace with the given content.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=write_file,
        requires_approval=True,
        legacy_tag_aliases=("write_file",),
    ),
    ToolSpec(
        name="edit_file",
        description="Replace a line range [start_line, end_line] (1-indexed, inclusive) in an existing file with new content.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "content": {"type": "string"},
            },
            "required": ["path", "start_line", "end_line", "content"],
        },
        handler=edit_file,
        requires_approval=True,
        legacy_tag_aliases=("edit_file",),
    ),
    ToolSpec(
        name="delete_file",
        description="Delete a file or directory in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=delete_file,
        requires_approval=True,
        legacy_tag_aliases=("delete_file",),
    ),
    ToolSpec(
        name="move_file",
        description="Move or rename a file/directory within the workspace.",
        parameters={
            "type": "object",
            "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
            "required": ["source", "destination"],
        },
        handler=move_file,
        requires_approval=True,
        legacy_tag_aliases=("move_file",),
    ),
    ToolSpec(
        name="copy_file",
        description="Copy a file within the workspace.",
        parameters={
            "type": "object",
            "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
            "required": ["source", "destination"],
        },
        handler=copy_file,
        legacy_tag_aliases=("copy_file",),
    ),
    ToolSpec(
        name="make_directory",
        description="Create a directory (and parents) in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=make_directory,
        legacy_tag_aliases=("make_directory",),
    ),
    ToolSpec(
        name="list_directory",
        description="List the contents of a directory in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
        handler=list_directory,
        legacy_tag_aliases=("list_directory",),
    ),
    ToolSpec(
        name="stat_path",
        description="Get metadata (type, size, modified time) about a path in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=stat_path,
        legacy_tag_aliases=("stat_path",),
    ),
    ToolSpec(
        name="view_project_tree",
        description="View a tree listing of the workspace's file structure.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=view_project_tree,
        legacy_tag_aliases=("view_project_tree",),
    ),
]
