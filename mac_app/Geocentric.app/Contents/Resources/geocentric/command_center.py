from __future__ import annotations

import shlex
import subprocess
import signal
import threading
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional


@dataclass
class CommandRecord:
    id: str
    cmd: str
    pid: Optional[int]
    status: str
    cwd: Optional[str]


_PROCS: Dict[str, subprocess.Popen] = {}
_RECORDS: Dict[str, CommandRecord] = {}
_LOCK = threading.Lock()


def start_command(cmd: str, cwd: Optional[str] = None) -> CommandRecord:
    """Start a command in background and return a handle."""
    with _LOCK:
        run_id = str(uuid.uuid4())
        try:
            parts = shlex.split(cmd)
        except Exception:
            parts = [cmd]
        proc = subprocess.Popen(parts, cwd=cwd or None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        _PROCS[run_id] = proc
        rec = CommandRecord(id=run_id, cmd=cmd, pid=proc.pid, status="running", cwd=cwd)
        _RECORDS[run_id] = rec
        return rec


def stop_command(run_id: str) -> CommandRecord:
    with _LOCK:
        proc = _PROCS.get(run_id)
        rec = _RECORDS.get(run_id)
        if not proc or not rec:
            raise KeyError("Unknown run id")
        proc.terminate()
        rec.status = "terminated"
        return rec


def kill_command(run_id: str) -> CommandRecord:
    with _LOCK:
        proc = _PROCS.get(run_id)
        rec = _RECORDS.get(run_id)
        if not proc or not rec:
            raise KeyError("Unknown run id")
        proc.kill()
        rec.status = "killed"
        return rec


def pause_command(run_id: str) -> CommandRecord:
    with _LOCK:
        proc = _PROCS.get(run_id)
        rec = _RECORDS.get(run_id)
        if not proc or not rec:
            raise KeyError("Unknown run id")
        try:
            proc.send_signal(signal.SIGSTOP)
            rec.status = "paused"
        except Exception:
            rec.status = "pause_failed"
        return rec


def resume_command(run_id: str) -> CommandRecord:
    with _LOCK:
        proc = _PROCS.get(run_id)
        rec = _RECORDS.get(run_id)
        if not proc or not rec:
            raise KeyError("Unknown run id")
        try:
            proc.send_signal(signal.SIGCONT)
            rec.status = "running"
        except Exception:
            rec.status = "resume_failed"
        return rec


def list_commands() -> Dict[str, dict]:
    with _LOCK:
        out = {}
        for rid, rec in _RECORDS.items():
            proc = _PROCS.get(rid)
            if proc:
                alive = proc.poll() is None
                rec.status = rec.status if alive else ("exited" if proc.returncode == 0 else f"exited:{proc.returncode}")
            out[rid] = asdict(rec)
        return out
