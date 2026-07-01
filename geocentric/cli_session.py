"""Geocentric Code CLI — session persistence, compaction, and checkpoints."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


SESSIONS_DIR = Path(os.path.expanduser("~/.geocentric/sessions"))
CHECKPOINTS_DIR = Path(os.path.expanduser("~/.geocentric/checkpoints"))
HISTORY_DIR = Path(os.path.expanduser("~/.geocentric/history"))


@dataclass
class SessionState:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "default"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[dict[str, str]] = field(default_factory=list)
    conversation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    model: str = "geocentric-local"
    model_mode: str = "thinking"
    effort: str = "medium"
    plan_mode: bool = False
    auto_mode: bool = True
    token_usage: int = 0
    extra_dirs: list[str] = field(default_factory=list)
    summary: str = ""

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def save_session(state: SessionState) -> None:
    ensure_dirs()
    state.touch()
    path = session_path(state.id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state.to_dict(), fh, indent=2)


def save_conversation_history(chat_id: str, messages: list[dict[str, str]]) -> None:
    ensure_dirs()
    if not chat_id:
        return
    path = HISTORY_DIR / f"{chat_id}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(messages, fh, indent=2)


def load_conversation_history(chat_id: str) -> list[dict[str, str]]:
    if not chat_id:
        return []
    path = HISTORY_DIR / f"{chat_id}.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def load_session(session_id: str) -> Optional[SessionState]:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return SessionState.from_dict(json.load(fh))
    except Exception:
        return None


def list_sessions() -> list[SessionState]:
    ensure_dirs()
    sessions: list[SessionState] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                sessions.append(SessionState.from_dict(json.load(fh)))
        except Exception:
            continue
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def compact_messages(messages: list[dict[str, str]], instructions: str = "") -> tuple[list[dict[str, str]], str]:
    if len(messages) <= 4:
        return messages, ""
    kept = messages[:2] + messages[-4:]
    dropped = len(messages) - len(kept)
    summary = instructions or f"Compacted {dropped} earlier messages. Recent context preserved."
    compacted = kept[:2] + [{"role": "system", "content": f"[Session summary] {summary}"}] + kept[2:]
    return compacted, summary


def save_checkpoint(state: SessionState) -> str:
    ensure_dirs()
    cp_id = uuid.uuid4().hex[:10]
    path = CHECKPOINTS_DIR / f"{state.id}_{cp_id}.json"
    payload = {
        "checkpoint_id": cp_id,
        "session_id": state.id,
        "saved_at": time.time(),
        "messages": state.messages,
        "conversation_id": state.conversation_id,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return cp_id


def list_checkpoints(session_id: str) -> list[dict[str, Any]]:
    ensure_dirs()
    out: list[dict[str, Any]] = []
    for path in CHECKPOINTS_DIR.glob(f"{session_id}_*.json"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    out.sort(key=lambda x: x.get("saved_at", 0), reverse=True)
    return out


def restore_checkpoint(session_id: str, checkpoint_id: str) -> Optional[dict[str, Any]]:
    path = CHECKPOINTS_DIR / f"{session_id}_{checkpoint_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def rewind_messages(messages: list[dict[str, str]], turns: int = 1) -> list[dict[str, str]]:
    out = list(messages)
    removed = 0
    while out and removed < turns:
        if out[-1].get("role") == "assistant":
            out.pop()
            removed += 1
            if out and out[-1].get("role") == "user":
                out.pop()
        else:
            out.pop()
    return out
