"""Sandbox-safe path resolution shared by every filesystem-touching tool.

Mirrors the semantics already used by geocentric/server.py's tool handlers
(path_is_inside / workspace_resolve) so behavior is familiar, but is a fresh,
standalone implementation with no import dependency on server.py -- pulling
in server.py would drag in FastAPI/uvicorn/SQLite-init at import time, which
is exactly the startup-latency cost the in-process CLI core exists to avoid.
"""

from __future__ import annotations

from pathlib import Path


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_in_workspace(workspace_dir: Path, rel_path: str) -> Path:
    rel = (rel_path or ".").strip().strip('"') or "."
    target = (workspace_dir / rel).resolve()
    if not path_is_inside(target, workspace_dir):
        raise ValueError(f"Sandbox escape attempt detected: {rel}")
    return target


def safe_text_snapshot(path: Path, max_bytes: int = 500_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
