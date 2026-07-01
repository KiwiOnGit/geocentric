from __future__ import annotations

import argparse
import json
import urllib.request
import urllib.error
import urllib.parse
import html
import time
import asyncio
import ast
import queue
import threading
import copy
import shlex
import base64
import mimetypes
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional
import sys
import sqlite3
import hashlib
import os
import secrets
import uuid
import re
import difflib
from collections import defaultdict

from pydantic import BaseModel, Field

DEFAULT_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "1024505963248-dummygoogleclientidforgeocentric.apps.googleusercontent.com")
DEFAULT_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "GOCSPX-dummysecret")

# Global thread-safe logging redirection class
class ServerLogger:
    def __init__(self, original_stdout, log_file_path: Path = Path("log.txt"), max_size_bytes: int = 102400):
        self.terminal = original_stdout
        self.log_file_path = log_file_path
        self.max_size_bytes = max_size_bytes
        self.lock = threading.Lock()

    def write(self, message):
        if message and _should_suppress_server_console(message):
            if _server_debug_stream_enabled():
                self.terminal.write(message)
                self.terminal.flush()
            self._append_log(message)
            return

        # Always output to the actual terminal
        self.terminal.write(message)
        self.terminal.flush()
        self._append_log(message)

    def _append_log(self, message):
        # Append to log.txt with timestamp and safety size limits
        if message and message.strip():
            with self.lock:
                try:
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                    log_line = f"[{timestamp}] {message.strip()}\n"
                    with open(self.log_file_path, "a", encoding="utf-8", errors="ignore") as f:
                        f.write(log_line)

                    # Cap file size to stay super low (max 100KB)
                    if self.log_file_path.exists() and self.log_file_path.stat().st_size > self.max_size_bytes:
                        # Keep only the last 400 lines
                        content = self.log_file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        self.log_file_path.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8", errors="ignore")
                except Exception:
                    pass

    def flush(self):
        self.terminal.flush()

    def isatty(self):
        if hasattr(self.terminal, "isatty"):
            return self.terminal.isatty()
        return False

    def fileno(self):
        if hasattr(self.terminal, "fileno"):
            return self.terminal.fileno()
        raise OSError("fileno not supported")

    def __getattr__(self, attr):
        return getattr(self.terminal, attr)

# Redirect stdout and stderr globally
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
sys.stdout = ServerLogger(sys.stdout)
sys.stderr = ServerLogger(sys.stderr)


_STREAM_SUPPRESS_MARKERS = (
    "--- AI STREAM",
    "--- LOCAL AI STREAM",
    "--- API OLLAMA STREAM",
    "--- API LOCAL MODEL STREAM",
    "[AI REASONING START]",
    "[AI REASONING END]",
    "Proxying request to local Ollama",
)


def _server_debug_stream_enabled() -> bool:
    return os.environ.get("GEOCENTRIC_DEBUG_STREAM", "").lower() in {"1", "true", "yes", "on"}


def _should_suppress_server_console(message: str) -> bool:
    if _server_debug_stream_enabled():
        return False
    if os.environ.get("GEOCENTRIC_SUPPRESS_STREAM", "1").lower() in {"1", "true", "yes", "on"}:
        return any(marker in (message or "") for marker in _STREAM_SUPPRESS_MARKERS)
    return False


def _server_stream_write(text: str) -> None:
    """Write model stream tokens to console only in debug mode."""
    if not text or not _server_debug_stream_enabled():
        return
    _ORIGINAL_STDOUT.write(text)
    _ORIGINAL_STDOUT.flush()


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    def clean_result_text(value: str) -> str:
        return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or ""))).strip()

    def normalize_result_url(raw_url: str) -> str:
        raw_url = html.unescape(urllib.parse.unquote(raw_url or ""))
        parsed = urllib.parse.urlparse(raw_url)
        query_values = urllib.parse.parse_qs(parsed.query)
        if "uddg" in query_values and query_values["uddg"]:
            return urllib.parse.unquote(query_values["uddg"][0])
        if raw_url.startswith("//duckduckgo.com/l/?"):
            query_values = urllib.parse.parse_qs(urllib.parse.urlparse("https:" + raw_url).query)
            if "uddg" in query_values and query_values["uddg"]:
                return urllib.parse.unquote(query_values["uddg"][0])
        return raw_url

    def request_text(url: str, timeout: int = 10) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(1_200_000).decode("utf-8", errors="ignore")

    def parse_duckduckgo(body: str) -> List[Dict[str, str]]:
        results = []
        seen = set()
        blocks = re.split(r'<div[^>]+class="[^"]*(?:result|web-result)[^"]*"[^>]*>', body, flags=re.IGNORECASE)
        for block in blocks[1:]:
            link_match = re.search(
                r'<a[^>]+class="[^"]*(?:result__a|result-link|result-title)[^"]*"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>',
                block,
                re.IGNORECASE,
            ) or re.search(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', block, re.IGNORECASE)
            if not link_match:
                continue
            url = normalize_result_url(link_match.group(1))
            if not url.startswith(("http://", "https://")) or "duckduckgo.com/y.js" in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            title = clean_result_text(link_match.group(2))
            snippet_match = re.search(
                r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</a>|<div[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</div>|<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>([\s\S]*?)</td>',
                block,
                re.IGNORECASE,
            )
            snippet = clean_result_text(next((g for g in (snippet_match.groups() if snippet_match else []) if g), ""))
            if title:
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results

    def parse_bing(body: str) -> List[Dict[str, str]]:
        results = []
        seen = set()
        for match in re.finditer(r'<li class="b_algo"[\s\S]*?</li>', body, re.IGNORECASE):
            block = match.group(0)
            link_match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', block, re.IGNORECASE)
            if not link_match:
                continue
            url = html.unescape(link_match.group(1))
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            snippet_match = re.search(r'<p[^>]*>([\s\S]*?)</p>', block, re.IGNORECASE)
            results.append({
                "title": clean_result_text(link_match.group(2)),
                "url": url,
                "snippet": clean_result_text(snippet_match.group(1) if snippet_match else ""),
            })
            if len(results) >= max_results:
                break
        return results

    query = re.sub(r"\s+", " ", query or "").strip()
    if not query:
        return []
    sources = [
        "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
        "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query),
        "https://www.bing.com/search?q=" + urllib.parse.quote(query),
    ]
    for index, url in enumerate(sources):
        try:
            body = request_text(url)
            results = parse_bing(body) if "bing.com" in url else parse_duckduckgo(body)
            if results:
                return results[:max_results]
        except Exception as e:
            print(f"Search source {index + 1} failed for '{query}': {e}")
            continue
    return []


def clean_image_query(query: str) -> str:
    # Remove common request patterns
    patterns = [
        r"\bshow me (?:images|pictures|photos|pics|visuals) of\b",
        r"\bshow (?:images|pictures|photos|pics|visuals) of\b",
        r"\bfind (?:images|pictures|photos|pics|visuals) of\b",
        r"\bsearch (?:images|pictures|photos|pics|visuals) of\b",
        r"\b(?:images|pictures|photos|pics|visuals) of\b",
        r"\b(?:image|picture|photo|pic|visual) of\b",
        r"\bshow me\b",
        r"\bshow\b",
    ]
    for pattern in patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE)
    return query.strip()


IMAGE_INTENT_RE = re.compile(
    r"\b(image|images|picture|pictures|photo|photos|pic|pics|visual|visuals|"
    r"show me|what does .+ look like|what do .+ look like)\b",
    re.IGNORECASE,
)


def user_wants_images(text: str) -> bool:
    return bool(IMAGE_INTENT_RE.search(text or ""))


def latest_user_text(messages: List[Mapping[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def latest_user_image_query(messages: List[Mapping[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            query = clean_image_query(str(msg.get("content") or ""))
            return query[:120].strip()
    return ""


def extract_image_search_query(text: str) -> str:
    match = re.search(r"<image_search\b[^>]*>([\s\S]*?)</image_search>", text or "", flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\[image_search\]([\s\S]*?)\[/image_search\]", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return clean_image_query(re.sub(r"\s+", " ", match.group(1)).strip())[:120].strip()
import queue as py_queue
import threading
import asyncio

def run_generator_in_thread(gen_func, *args, **kwargs):
    q = py_queue.Queue()
    def worker():
        try:
            for item in gen_func(*args, **kwargs):
                q.put((True, item))
        except Exception as e:
            q.put((False, e))
        finally:
            q.put((None, None))
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return q

async def async_generator_from_queue(q):
    while True:
        status, item = await asyncio.to_thread(q.get)
        if status is None:
            break
        if not status:
            raise item
        yield item


def extract_web_search_query(text: str) -> str:
    match = re.search(r"<search\b[^>]*>([\s\S]*?)</search>", text or "", flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\[search\]([\s\S]*?)\[/search\]", text or "", flags=re.IGNORECASE)
    if not match:
        match = re.search(r"call:search\s*\{\s*query:\s*([\s\S]*?)\s*\}", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    q = match.group(1).strip()
    if (q.startswith('"') and q.endswith('"')) or (q.startswith("'") and q.endswith("'")):
        q = q[1:-1].strip()
    return re.sub(r"\s+", " ", q).strip()[:160]



def image_gallery_block(query: str, count: int = 6) -> str:
    if not query:
        return ""
    image_query = query
    if re.search(r"\b(movie|film|trailer|series|show|game)\b", image_query, re.IGNORECASE):
        image_query = f"{image_query} official poster still trailer"
    images = search_bing_images(image_query, count)
    if not images:
        return ""
    return "\n\n<images>\n" + "\n".join(images) + "\n</images>"


def search_bing_images(query: str, count: int = 3) -> list[str]:
    try:
        cleaned_query = clean_image_query(query)
        print(f"Fetching images for query: '{cleaned_query}' (original: '{query}')")
        url = "https://www.bing.com/images/search?q=" + urllib.parse.quote(cleaned_query)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read().decode("utf-8")
        urls = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', body)
        results = []
        seen = set()
        for u in urls:
            lowered = u.lower()
            if (
                u not in seen
                and not any(ext in lowered for ext in ['.svg', '.gif'])
                and "example.com" not in lowered
                and "placehold.co" not in lowered
                and "placeholder" not in lowered
            ):
                seen.add(u)
                results.append(u)
                if len(results) >= count:
                    break
        return results
    except Exception as e:
        print("Error fetching Bing images:", e)
        return []


import shutil

TERMINAL_SESSIONS: Dict[str, "SandboxTerminalSession"] = {}
TERMINAL_SESSIONS_LOCK = threading.Lock()
TERMINAL_TTL_SECONDS = 30 * 60
BACKGROUND_PROCESSES: Dict[str, "BackgroundProcess"] = {}
BACKGROUND_PROCESSES_LOCK = threading.Lock()
IDLE_MONITOR_STARTED = False
IDLE_MONITOR_LOCK = threading.Lock()
IDLE_REVIEW_THRESHOLD_SECONDS = 30 * 60
IDLE_REVIEW_COOLDOWN_SECONDS = 6 * 60 * 60
AGENT_JOB_STALE_SECONDS = 7 * 24 * 60 * 60
MAX_GENERATION_TOKENS = 2_147_483_647


def env_int(name: str, default: int, minimum: int = 1, maximum: int = MAX_GENERATION_TOKENS) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


DEFAULT_CHAT_MAX_TOKENS = env_int("GEOCENTRIC_CHAT_MAX_TOKENS", 131_072)
DEFAULT_AGENT_MAX_TOKENS = env_int("GEOCENTRIC_AGENT_MAX_TOKENS", MAX_GENERATION_TOKENS)
DEFAULT_CHAT_CONTINUATION_LIMIT = env_int("GEOCENTRIC_CHAT_CONTINUATION_LIMIT", 8, maximum=1_000_000)
DEFAULT_AGENT_CONTINUATION_LIMIT = env_int("GEOCENTRIC_AGENT_CONTINUATION_LIMIT", 15, maximum=1_000_000)

WORKSPACE_MUTATION_TAGS = (
    "write_file",
    "edit_file",
    "delete_file",
    "make_directory",
    "copy_file",
    "move_file",
    "download_url",
    "run_command",
    "install_package",
)
WORKSPACE_TEST_TAGS = (
    "run_file",
    "run_command",
    "agent_terminal",
    "run_bg_command",
    "check_process",
    "capture_view",
    "port_check",
    "http_request",
)
WORKSPACE_TOOL_TAGS = WORKSPACE_MUTATION_TAGS + WORKSPACE_TEST_TAGS + (
    "read_file",
    "view_project_tree",
    "list_directory",
    "stat_path",
    "search",
    "browse_url",
    "system_info",
    "list_processes",
    "update_roadmap",
)


def generation_token_budget(workspace_context_needed: bool) -> int:
    return DEFAULT_AGENT_MAX_TOKENS if workspace_context_needed else DEFAULT_CHAT_MAX_TOKENS


def continuation_turn_limit(workspace_context_needed: bool) -> int:
    return DEFAULT_AGENT_CONTINUATION_LIMIT if workspace_context_needed else DEFAULT_CHAT_CONTINUATION_LIMIT


PROJECT_WORKSPACE_OVERRIDES: Dict[tuple[str, str], Path] = {}
PROJECT_WORKSPACE_OVERRIDES_LOCK = threading.Lock()


def workspace_dir_for(user_id: int | str, chat_id: str) -> Path:
    key = (str(user_id), str(chat_id))
    with PROJECT_WORKSPACE_OVERRIDES_LOCK:
        override = PROJECT_WORKSPACE_OVERRIDES.get(key)
    if override and override.exists() and override.is_dir():
        return override
    return Path("workspaces") / str(user_id) / chat_id


def request_is_local(request: Any) -> bool:
    client_ip = getattr(getattr(request, "client", None), "host", "127.0.0.1")
    return client_ip in {"127.0.0.1", "::1", "localhost", "testclient"}


def register_project_workspace(user_id: int | str, chat_id: str, project_path: Optional[str], request: Any) -> Optional[Path]:
    if not project_path:
        return None
    if not request_is_local(request):
        raise HTTPException(status_code=403, detail="Project folders can only be bound from the local desktop app.")

    resolved = Path(project_path).expanduser().resolve()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create project folder: {exc}")

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Project path must be a directory.")
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise HTTPException(status_code=403, detail="Project directory is not readable and writable.")

    key = (str(user_id), str(chat_id))
    with PROJECT_WORKSPACE_OVERRIDES_LOCK:
        PROJECT_WORKSPACE_OVERRIDES[key] = resolved
    return resolved


LOCAL_CLI_USER_ID = "cli-local"


def is_cli_client_request(request: Any) -> bool:
    return (getattr(request, "headers", {}).get("X-Geocentric-Client") or "").lower() == "cli"


def cli_local_user() -> Dict[str, str]:
    return {"id": LOCAL_CLI_USER_ID, "name": "CLI", "email": "cli@local"}


def build_cli_sandbox_instruction(workspace_dir: Path) -> str:
    ws = str(workspace_dir)
    return (
        f"\n[CLI WORKSPACE — LOCAL PROJECT FOLDER]\n"
        f"Your writable workspace is: {ws}\n"
        f"When the user asks to create, edit, read, list, or run files, you MUST use tool tags in the same response. "
        f"Never claim a file was created unless you emitted <write_file> (or the appropriate tool tag).\n\n"
        f"Create/overwrite: <write_file filename=\"hello.txt\">content here</write_file>\n"
        f"Read: <read_file filename=\"hello.txt\" />\n"
        f"List directory: <list_directory path=\".\" />\n"
        f"Shell command: <run_command>ls -la</run_command>\n"
        f"Edit lines: <edit_file filename=\"file.py\">...</edit_file>\n\n"
        f"Before each tool action emit a specific <status>short description</status>.\n"
        f"After writing a file, tell the user the full path: {ws}/filename\n"
        f"Keep scope minimal — if they ask for one file, create only that file.\n"
        f"Do not say you lack filesystem access; use the tools above.\n"
    )


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def template_dirs() -> list[Path]:
    candidates = [
        Path(__file__).parent / "templates",
        Path.cwd() / "templates",
        Path(__file__).resolve().parent.parent / "templates",
    ]
    seen = set()
    result = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_dir():
            result.append(resolved)
    return result


def copy_workspace_templates(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for template_dir in template_dirs():
        for t_file in template_dir.glob("*.md"):
            dest_file = workspace_dir / t_file.name
            if not dest_file.exists():
                try:
                    shutil.copy(t_file, dest_file)
                except Exception as exc:
                    print(f"Failed to copy template {t_file}: {exc}")


def normalize_python_command(command: str) -> tuple[str, str]:
    display_command = command
    normalized = re.sub(r"^python(\s|$)", shlex.quote(sys.executable) + r"\1", command.strip(), count=1)
    return display_command, normalized


def append_error_search_context(output: str) -> str:
    if not sandbox_execution_needs_correction(output):
        return output
    if "[AGENT TERMINAL INPUT REQUIRED]" in output:
        return output

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    query = ""
    for line in reversed(lines):
        if "error" in line.lower() or "traceback" in line.lower() or "exception" in line.lower():
            query = line[:220]
            break
    if not query and lines:
        query = lines[-1][:220]
    if not query:
        return output

    results = search_duckduckgo(query, max_results=3)
    if not results:
        return output

    context = "\n\n--- AUTOMATIC ERROR SEARCH RESULTS ---\n"
    context += "\n".join(
        f"- {r['title']}: {r['url']}\n  {r['snippet']}"
        for r in results
    )
    return output + context


def read_python_source_for_check(target_path: Path, filename: str) -> tuple[bool, str, str]:
    try:
        source = target_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return False, "", f"ERROR reading '{filename}': {exc}"

    try:
        compile(source, str(target_path), "exec")
    except SyntaxError as exc:
        location = f"line {exc.lineno}"
        if exc.offset:
            location += f", column {exc.offset}"
        return False, source, f"ERROR checking syntax in '{filename}' at {location}: {exc.msg}"

    return True, source, ""


def python_script_uses_input(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "input(" in source

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "input":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "input":
            return True
    return False


def terminal_tag_for(filename: str) -> str:
    escaped = html.escape(filename, quote=True)
    return f'<terminal filename="{escaped}" />'


class SandboxTerminalSession:
    def __init__(self, user_id: int | str, chat_id: str, filename: str, workspace_dir: Path, target_path: Path):
        self.id = uuid.uuid4().hex
        self.user_id = str(user_id)
        self.chat_id = chat_id
        self.filename = filename
        self.workspace_dir = workspace_dir
        self.target_path = target_path
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.returncode: Optional[int] = None
        self.output: "queue.Queue[str]" = queue.Queue()
        self.process: Optional[subprocess.Popen[str]] = None
        self.reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(self.target_path)],
            cwd=str(self.workspace_dir.resolve()),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self) -> None:
        try:
            if not self.process or not self.process.stdout:
                return
            while True:
                chunk = self.process.stdout.read(1)
                if chunk == "":
                    break
                self.output.put(chunk)
                self.updated_at = time.time()
        except Exception as exc:
            self.output.put(f"\n[terminal read error: {exc}]\n")
        finally:
            if self.process:
                self.returncode = self.process.wait()
            self.updated_at = time.time()

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def write_input(self, value: str) -> None:
        if not self.process or not self.process.stdin or not self.is_running():
            raise RuntimeError("Terminal process is not running.")
        self.process.stdin.write(value)
        self.process.stdin.flush()
        self.updated_at = time.time()

    def stop(self) -> None:
        if not self.process or not self.is_running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.returncode = self.process.returncode
        self.updated_at = time.time()

    def drain_output(self) -> str:
        chunks = []
        while True:
            try:
                chunks.append(self.output.get_nowait())
            except queue.Empty:
                break
        return "".join(chunks)


class BackgroundProcess:
    def __init__(self, user_id: int | str, chat_id: str, command: str, workspace_dir: Path):
        self.id = uuid.uuid4().hex
        self.user_id = str(user_id)
        self.chat_id = chat_id
        self.command = command
        self.workspace_dir = workspace_dir
        self.started_at = time.time()
        self.updated_at = self.started_at
        self.logs: list[str] = []
        self.process: Optional[subprocess.Popen[str]] = None
        self.reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        _, normalized = normalize_python_command(self.command)
        self.process = subprocess.Popen(
            normalized,
            shell=True,
            cwd=str(self.workspace_dir.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.reader_thread = threading.Thread(target=self._read_logs, daemon=True)
        self.reader_thread.start()

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    def _read_logs(self) -> None:
        if not self.process or not self.process.stdout:
            return
        try:
            for line in self.process.stdout:
                self.logs.append(line.rstrip("\n"))
                self.logs = self.logs[-500:]
                self.updated_at = time.time()
        except Exception as exc:
            self.logs.append(f"[process log read error: {exc}]")
        finally:
            self.updated_at = time.time()

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def returncode(self) -> Optional[int]:
        if not self.process:
            return None
        return self.process.poll()

    def last_logs(self, count: int = 20) -> str:
        lines = self.logs[-count:]
        return "\n".join(lines) if lines else "(no logs yet)"

    def stop(self) -> None:
        if not self.process or not self.is_running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.updated_at = time.time()


def workspace_tree(workspace_dir: Path, max_depth: int = 5, max_entries: int = 300) -> str:
    skip_names = {".git", "__pycache__", ".venv", "venv", "node_modules", ".DS_Store"}
    lines: list[str] = [f"{workspace_dir.name}/"]
    seen = 0

    def fmt_size(path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "?"
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"

    def walk(path: Path, prefix: str = "", depth: int = 0) -> None:
        nonlocal seen
        if seen >= max_entries:
            return
        try:
            children = [
                child for child in path.iterdir()
                if child.name not in skip_names and not child.name.startswith(".")
            ]
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

    walk(workspace_dir)
    return "\n".join(lines)


def workspace_resolve(workspace_dir: Path, rel_path: str) -> Path:
    rel = (rel_path or ".").strip().strip('"') or "."
    target = (workspace_dir / rel).resolve()
    if not path_is_inside(target, workspace_dir):
        raise ValueError(f"Sandbox escape attempt detected: {rel}")
    return target


def list_directory_tool(workspace_dir: Path, rel_path: str = ".", max_entries: int = 120) -> str:
    try:
        target = workspace_resolve(workspace_dir, rel_path)
    except ValueError as exc:
        return f"[LIST DIRECTORY ERROR] {exc}"
    if not target.exists():
        return f"[LIST DIRECTORY ERROR] Path does not exist: {rel_path}"
    if not target.is_dir():
        return f"[LIST DIRECTORY ERROR] Path is not a directory: {rel_path}"
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        rows = []
        for child in children[:max_entries]:
            kind = "dir" if child.is_dir() else "file"
            size = child.stat().st_size if child.is_file() else 0
            rows.append(f"- {kind}: {child.name}{'/' if child.is_dir() else ''} ({size} bytes)")
        if len(children) > max_entries:
            rows.append(f"... {len(children) - max_entries} more entries")
        return f"[LIST DIRECTORY RESULT] {rel_path or '.'}\n" + ("\n".join(rows) if rows else "(empty)")
    except Exception as exc:
        return f"[LIST DIRECTORY ERROR] Failed to list {rel_path}: {exc}"


def stat_path_tool(workspace_dir: Path, rel_path: str) -> str:
    try:
        target = workspace_resolve(workspace_dir, rel_path)
    except ValueError as exc:
        return f"[STAT PATH ERROR] {exc}"
    if not target.exists():
        return f"[STAT PATH ERROR] Path does not exist: {rel_path}"
    try:
        st = target.stat()
        return (
            f"[STAT PATH RESULT] {rel_path}\n"
            f"Type: {'directory' if target.is_dir() else 'file'}\n"
            f"Size: {st.st_size} bytes\n"
            f"Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}\n"
            f"Resolved: {target}"
        )
    except Exception as exc:
        return f"[STAT PATH ERROR] Failed to stat {rel_path}: {exc}"


def download_url_to_workspace(workspace_dir: Path, url: str, rel_path: str, max_bytes: int = 50 * 1024 * 1024) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"[DOWNLOAD URL ERROR] Unsupported URL scheme for '{url}'."
    try:
        target = workspace_resolve(workspace_dir, rel_path)
    except ValueError as exc:
        return f"[DOWNLOAD URL ERROR] {exc}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Geocentric-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                return f"[DOWNLOAD URL ERROR] Remote file is larger than {max_bytes} bytes."
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            return f"[DOWNLOAD URL ERROR] Download exceeded {max_bytes} bytes."
        old_text = _safe_text_snapshot(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        new_text = data.decode("utf-8", errors="ignore") if len(data) <= 240_000 else ""
        if new_text or old_text:
            record_workspace_diff(workspace_dir, rel_path, old_text, new_text, "modified" if old_text else "added")
        return f"[DOWNLOAD URL SUCCESS] Saved {len(data)} bytes from {url} to {rel_path}"
    except Exception as exc:
        return f"[DOWNLOAD URL ERROR] Failed to download {url}: {exc}"


def browse_url_text(url: str, max_chars: int = 12000) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"[BROWSE URL ERROR] Unsupported URL scheme for '{url}'. Use http or https."
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(1_500_000).decode(charset, errors="ignore")
            content_type = response.headers.get("content-type", "")
    except Exception as exc:
        return f"[BROWSE URL ERROR] Failed to fetch '{url}': {exc}"

    if "text/html" in content_type or "<html" in body[:500].lower():
        try:
            from html.parser import HTMLParser

            class Extractor(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self.parts: list[str] = []
                    self.skip_depth = 0

                def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
                    if tag in {"script", "style", "noscript", "svg"}:
                        self.skip_depth += 1
                    if tag in {"p", "div", "section", "article", "header", "footer", "li", "br", "h1", "h2", "h3", "pre", "code"}:
                        self.parts.append("\n")

                def handle_endtag(self, tag: str) -> None:
                    if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
                        self.skip_depth -= 1
                    if tag in {"p", "div", "section", "article", "li", "pre", "h1", "h2", "h3"}:
                        self.parts.append("\n")

                def handle_data(self, data: str) -> None:
                    if not self.skip_depth:
                        text = re.sub(r"\s+", " ", data).strip()
                        if text:
                            self.parts.append(text)

            extractor = Extractor()
            extractor.feed(body)
            text = "\n".join(part for part in extractor.parts if part.strip())
            text = re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()
        except Exception:
            text = re.sub(r"<[^>]+>", " ", body)
            text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    else:
        text = body.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return f"[BROWSE URL RESULT] Extracted text from {url}:\n{text or '(empty response)'}"


def chromium_executable() -> Optional[str]:
    candidates = [
        os.environ.get("CHROME_BIN", ""),
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("chromium") or "",
        shutil.which("google-chrome") or "",
        shutil.which("chrome") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def capture_view(user_id: int | str, chat_id: str, url: str, filename: str) -> str:
    workspace_dir = workspace_dir_for(user_id, chat_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    out_path = (workspace_dir / filename).resolve()
    if not path_is_inside(out_path, workspace_dir):
        return f"[CAPTURE VIEW ERROR] Sandbox Escape Attempt Detected: {filename}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    browser_path = chromium_executable()
    if not browser_path:
        return "[CAPTURE VIEW ERROR] Chromium/Chrome was not found on this system."

    try:
        result = subprocess.run(
            [
                browser_path,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--window-size=1280,720",
                f"--screenshot={out_path}",
                url,
            ],
            cwd=str(workspace_dir.resolve()),
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return f"[CAPTURE VIEW ERROR] Timed out while capturing {url}."
    except Exception as exc:
        return f"[CAPTURE VIEW ERROR] Failed to capture {url}: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return f"[CAPTURE VIEW ERROR] Browser exited with code {result.returncode} while capturing {url}.\n{detail}"
    if not out_path.exists():
        return f"[CAPTURE VIEW ERROR] Browser did not create screenshot '{filename}'."
    return f"[CAPTURE VIEW RESULT] Saved screenshot of {url} to '{filename}' ({out_path.stat().st_size} bytes)."


def start_background_process(user_id: int | str, chat_id: str, command: str) -> str:
    workspace_dir = workspace_dir_for(user_id, chat_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    proc = BackgroundProcess(user_id, chat_id, command.strip(), workspace_dir)
    if not proc.command:
        return "[RUN BG COMMAND ERROR] No command provided."
    try:
        proc.start()
    except Exception as exc:
        return f"[RUN BG COMMAND ERROR] Failed to start `{command}`: {exc}"
    pid_key = str(proc.pid or proc.id)
    with BACKGROUND_PROCESSES_LOCK:
        BACKGROUND_PROCESSES[proc.id] = proc
        BACKGROUND_PROCESSES[pid_key] = proc
    return (
        f"[RUN BG COMMAND RESULT] Started `{command}` in the background.\n"
        f"PID: {pid_key}\n"
        f"Use <check_process pid=\"{pid_key}\" /> to read logs and <kill_process pid=\"{pid_key}\" /> to stop it."
    )


def get_background_process(pid: str, user_id: int | str, chat_id: str) -> Optional[BackgroundProcess]:
    with BACKGROUND_PROCESSES_LOCK:
        proc = BACKGROUND_PROCESSES.get(str(pid))
    if not proc or proc.user_id != str(user_id) or proc.chat_id != chat_id:
        return None
    return proc


def check_background_process(user_id: int | str, chat_id: str, pid: str) -> str:
    proc = get_background_process(pid, user_id, chat_id)
    if not proc:
        return f"[CHECK PROCESS ERROR] Process '{pid}' was not found for this chat."
    status = "running" if proc.is_running() else f"exited ({proc.returncode()})"
    return (
        f"[CHECK PROCESS RESULT] PID {pid} is {status}.\n"
        f"Command: `{proc.command}`\n"
        f"Last 20 log lines:\n{proc.last_logs(20)}"
    )


def kill_background_process(user_id: int | str, chat_id: str, pid: str) -> str:
    proc = get_background_process(pid, user_id, chat_id)
    if not proc:
        return f"[KILL PROCESS ERROR] Process '{pid}' was not found for this chat."
    proc.stop()
    with BACKGROUND_PROCESSES_LOCK:
        for key, value in list(BACKGROUND_PROCESSES.items()):
            if value is proc:
                BACKGROUND_PROCESSES.pop(key, None)
    return f"[KILL PROCESS RESULT] Stopped process '{pid}' for `{proc.command}`."


def owned_system_info() -> str:
    import platform
    import socket

    try:
        mem = psutil.virtual_memory()
        memory_text = f"{mem.used / (1024 ** 3):.1f}GB used / {mem.total / (1024 ** 3):.1f}GB total"
    except Exception:
        memory_text = "unavailable"

    try:
        disk = shutil.disk_usage(Path.cwd())
        disk_text = f"{disk.used / (1024 ** 3):.1f}GB used / {disk.total / (1024 ** 3):.1f}GB total"
    except Exception:
        disk_text = "unavailable"

    try:
        load = ", ".join(f"{value:.2f}" for value in os.getloadavg())
    except Exception:
        load = "unavailable"

    return (
        "[SYSTEM INFO RESULT]\n"
        f"Hostname: {socket.gethostname()}\n"
        f"Platform: {platform.platform()}\n"
        f"Python: {sys.version.split()[0]} ({sys.executable})\n"
        f"Working directory: {Path.cwd()}\n"
        f"CPU count: {os.cpu_count() or 'unknown'}\n"
        f"Load average: {load}\n"
        f"Memory: {memory_text}\n"
        f"Disk: {disk_text}"
    )


def list_owned_processes(user_id: int | str, chat_id: str) -> str:
    lines = ["[LIST PROCESSES RESULT]", "Workspace background processes:"]
    found = False
    with BACKGROUND_PROCESSES_LOCK:
        unique = {}
        for proc in BACKGROUND_PROCESSES.values():
            if proc.user_id == str(user_id) and proc.chat_id == chat_id:
                unique[proc.id] = proc
    for proc in unique.values():
        found = True
        pid = proc.pid or proc.id
        status = "running" if proc.is_running() else f"exited ({proc.returncode()})"
        lines.append(f"- {pid}: {status} :: {proc.command}")
    if not found:
        lines.append("- none")

    lines.append("\nTop system processes:")
    try:
        rows = []
        for process in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent"]):
            info = process.info
            rows.append(info)
        rows.sort(key=lambda item: (item.get("cpu_percent") or 0, item.get("memory_percent") or 0), reverse=True)
        for info in rows[:12]:
            lines.append(
                f"- pid={info.get('pid')} name={info.get('name')} status={info.get('status')} "
                f"cpu={info.get('cpu_percent') or 0:.1f}% mem={info.get('memory_percent') or 0:.1f}%"
            )
    except Exception as exc:
        lines.append(f"- unavailable: {exc}")
    return "\n".join(lines)


def check_port(host: str, port: str) -> str:
    import socket

    clean_host = host.strip() if host else "127.0.0.1"
    try:
        clean_port = int(port)
    except (TypeError, ValueError):
        return f"[PORT CHECK ERROR] Invalid port: {port}"
    if clean_port < 1 or clean_port > 65535:
        return f"[PORT CHECK ERROR] Port out of range: {clean_port}"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        result = sock.connect_ex((clean_host, clean_port))
        state = "open" if result == 0 else "closed"
        return f"[PORT CHECK RESULT] {clean_host}:{clean_port} is {state}."
    except Exception as exc:
        return f"[PORT CHECK ERROR] Failed checking {clean_host}:{clean_port}: {exc}"
    finally:
        sock.close()


def http_request_tool(url: str, method: str = "GET", body: str = "", max_chars: int = 6000) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"[HTTP REQUEST ERROR] Unsupported URL scheme for '{url}'. Use http or https."
    clean_method = (method or "GET").strip().upper()
    if clean_method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
        return f"[HTTP REQUEST ERROR] Unsupported method '{method}'."
    data = body.encode("utf-8") if body and clean_method not in {"GET", "HEAD"} else None
    headers = {"User-Agent": "Geocentric-Agent/1.0"}
    if data is not None:
        headers["Content-Type"] = "text/plain; charset=utf-8"
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=clean_method)
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(500_000)
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="ignore")
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"
            return (
                f"[HTTP REQUEST RESULT] {clean_method} {url}\n"
                f"Status: {response.status}\n"
                f"Content-Type: {response.headers.get('content-type', 'unknown')}\n"
                f"Body:\n{text if clean_method != 'HEAD' else '(HEAD response has no body)'}"
            )
    except urllib.error.HTTPError as exc:
        text = exc.read(100_000).decode(errors="ignore")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        return f"[HTTP REQUEST RESULT] {clean_method} {url}\nStatus: {exc.code}\nBody:\n{text}"
    except Exception as exc:
        return f"[HTTP REQUEST ERROR] Failed {clean_method} {url}: {exc}"


def update_roadmap_file(workspace_dir: Path, roadmap_md: str) -> str:
    agents_path = workspace_dir / "agents.md"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    existing = agents_path.read_text(encoding="utf-8", errors="ignore") if agents_path.exists() else ""
    section = "## Current Roadmap\n" + roadmap_md.strip() + "\n"
    if "## Current Roadmap" in existing:
        updated = re.sub(
            r"## Current Roadmap[\s\S]*?(?=\n## |\Z)",
            section.rstrip(),
            existing,
            flags=re.IGNORECASE,
        )
    else:
        updated = existing.rstrip() + ("\n\n" if existing.strip() else "") + section
    agents_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return "[UPDATE ROADMAP SUCCESS] Updated agents.md Current Roadmap."


def ensure_initial_roadmap(workspace_dir: Path, request_text: str) -> None:
    if read_workspace_roadmap(workspace_dir):
        return
    update_roadmap_file(
        workspace_dir,
        "- [ ] AI is analyzing the request and planning custom roadmap...",
    )


def safe_upload_filename(name: str, default: str = "upload.bin") -> str:
    cleaned = Path(name or default).name.strip().replace("\x00", "")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", cleaned)
    cleaned = cleaned.strip(" .")
    return cleaned or default


def decode_attachment_payload(attachment: Any, index: int) -> Optional[dict[str, Any]]:
    if isinstance(attachment, str):
        data_url = attachment
        mime = ""
        if data_url.startswith("data:") and "," in data_url:
            header, b64 = data_url.split(",", 1)
            mime = header[5:].split(";")[0]
        else:
            b64 = data_url
        ext = mimetypes.guess_extension(mime or "") or ".bin"
        name = f"upload-{index}{ext}"
    elif isinstance(attachment, Mapping):
        data_url = str(attachment.get("dataUrl") or attachment.get("data") or "")
        mime = str(attachment.get("type") or "")
        name = safe_upload_filename(str(attachment.get("name") or f"upload-{index}"))
        if not data_url:
            return None
        if not mime and data_url.startswith("data:"):
            mime = data_url[5:].split(";", 1)[0]
    else:
        return None

    try:
        if data_url.startswith("data:") and "," in data_url:
            header, b64 = data_url.split(",", 1)
            if ";base64" not in header.lower():
                raw = urllib.parse.unquote_to_bytes(b64)
            else:
                raw = base64.b64decode(b64, validate=False)
        else:
            raw = base64.b64decode(data_url, validate=False)
    except Exception:
        return None

    if len(raw) > 75 * 1024 * 1024:
        return None
    return {"name": name, "mime": mime or "application/octet-stream", "bytes": raw}


def extract_zip_safely(zip_path: Path, extract_root: Path, workspace_dir: Path) -> list[str]:
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if len(extracted) >= 500:
                break
            rel_name = Path(info.filename)
            if rel_name.is_absolute() or any(part in {"..", ""} for part in rel_name.parts):
                continue
            target_path = (extract_root / rel_name).resolve()
            if not path_is_inside(target_path, workspace_dir):
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target_path.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            extracted.append(target_path.relative_to(workspace_dir).as_posix())
    return extracted


def save_uploaded_attachments(user_id: int | str, chat_id: str, messages: list[dict[str, Any]], attachments: Optional[list[Any]] = None) -> list[str]:
    workspace_dir = workspace_dir_for(user_id, chat_id).resolve()
    upload_dir = workspace_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    candidates: list[Any] = []
    if attachments:
        candidates.extend(attachments)
    for message in messages:
        msg_attachments = message.get("attachments")
        if isinstance(msg_attachments, list):
            candidates.extend(msg_attachments)

    seen_digests: set[str] = set()
    for index, attachment in enumerate(candidates, 1):
        decoded = decode_attachment_payload(attachment, index)
        if not decoded:
            continue
        digest = hashlib.sha256(decoded["bytes"]).hexdigest()
        if digest in seen_digests:
            continue
        seen_digests.add(digest)
        filename = safe_upload_filename(decoded["name"], f"upload-{index}.bin")
        target_path = (upload_dir / filename).resolve()
        if not path_is_inside(target_path, workspace_dir):
            continue
        if target_path.exists():
            stem, suffix = target_path.stem, target_path.suffix
            target_path = (upload_dir / f"{stem}-{digest[:8]}{suffix}").resolve()
        target_path.write_bytes(decoded["bytes"])
        rel = target_path.relative_to(workspace_dir).as_posix()
        saved.append(rel)

        # Check if the file is a JSON file containing Google client credentials format
        if target_path.suffix.lower() == ".json":
            try:
                import json as py_json
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                parsed = py_json.loads(content)
                client_id = None
                client_secret = None
                if isinstance(parsed, dict):
                    if "installed" in parsed and isinstance(parsed["installed"], dict):
                        client_id = parsed["installed"].get("client_id")
                        client_secret = parsed["installed"].get("client_secret")
                    elif "web" in parsed and isinstance(parsed["web"], dict):
                        client_id = parsed["web"].get("client_id")
                        client_secret = parsed["web"].get("client_secret")
                    elif "client_id" in parsed and "client_secret" in parsed:
                        client_id = parsed.get("client_id")
                        client_secret = parsed.get("client_secret")
                
                if client_id and client_secret:
                    conn = sqlite3.connect("users.db")
                    cursor = conn.cursor()
                    cursor.execute("CREATE TABLE IF NOT EXISTS google_config (key TEXT PRIMARY KEY, value TEXT)")
                    cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_id', ?)", (client_id.strip(),))
                    cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_secret', ?)", (client_secret.strip(),))
                    conn.commit()
                    conn.close()
                    saved.append("[GOOGLE_CONFIG_AUTO_SUCCESS]")
                    print(f"[GOOGLE CONFIG] Successfully configured Google OAuth client from uploaded JSON file: {filename}")
            except Exception as e:
                print(f"[GOOGLE CONFIG ERROR] Failed to parse credentials from JSON attachment {filename}: {e}")

        is_zip = target_path.suffix.lower() == ".zip" or decoded["mime"] in {"application/zip", "application/x-zip-compressed"}
        if is_zip:
            extract_root = (upload_dir / f"{target_path.stem}_extracted").resolve()
            if path_is_inside(extract_root, workspace_dir):
                extract_root.mkdir(parents=True, exist_ok=True)
                try:
                    saved.extend(extract_zip_safely(target_path, extract_root, workspace_dir))
                except Exception as exc:
                    (extract_root / "ZIP_EXTRACT_ERROR.txt").write_text(str(exc), encoding="utf-8")
                    saved.append((extract_root / "ZIP_EXTRACT_ERROR.txt").relative_to(workspace_dir).as_posix())
    return saved


def redact_attachment_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = copy.deepcopy(messages)
    for message in redacted:
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            continue
        safe_items = []
        for index, attachment in enumerate(attachments, 1):
            if isinstance(attachment, Mapping):
                safe_items.append({
                    "name": safe_upload_filename(str(attachment.get("name") or f"upload-{index}")),
                    "type": str(attachment.get("type") or ""),
                    "size": attachment.get("size") or 0,
                })
            elif isinstance(attachment, str):
                safe_items.append({"name": f"upload-{index}", "type": "data-url", "size": len(attachment)})
        message["attachments"] = safe_items
    return redacted


class GoogleConfigRequest(BaseModel):
    clientId: str
    clientSecret: str

def get_google_credentials(user_id: str) -> Optional[str]:
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM google_credentials WHERE user_id = ?", (user_id,))
        cred = cursor.fetchone()
    except sqlite3.Error:
        conn.close()
        return None
    if not cred:
        conn.close()
        return None
        
    access_token = cred["access_token"]
    refresh_token = cred["refresh_token"]
    expiry = cred["token_expiry"]
    
    if expiry and expiry < time.time() + 60:
        try:
            cursor.execute("SELECT value FROM google_config WHERE key = 'client_id'")
            cid_row = cursor.fetchone()
            cursor.execute("SELECT value FROM google_config WHERE key = 'client_secret'")
            sec_row = cursor.fetchone()
        except sqlite3.Error:
            cid_row = None
            sec_row = None
        
        client_id = cid_row["value"] if cid_row else DEFAULT_CLIENT_ID
        client_secret = sec_row["value"] if sec_row else DEFAULT_CLIENT_SECRET
        
        if client_id and client_secret and refresh_token:
            try:
                refresh_data = urllib.parse.urlencode({
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token"
                }).encode("utf-8")
                
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=refresh_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST"
                )
                
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    new_access_token = resp_data["access_token"]
                    new_expiry = time.time() + float(resp_data.get("expires_in", 3600))
                    
                    cursor.execute("""
                        UPDATE google_credentials
                        SET access_token = ?, token_expiry = ?
                        WHERE user_id = ?
                    """, (new_access_token, new_expiry, user_id))
                    conn.commit()
                    access_token = new_access_token
            except Exception as e:
                print(f"Failed to refresh Google token for user {user_id}: {e}")
                conn.close()
                return None
    
    conn.close()
    return access_token

def gmail_list_messages_api(access_token: str, q: str = "", max_results: int = 10) -> str:
    try:
        params = {"maxResults": str(max_results)}
        if q:
            params["q"] = q
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            messages = data.get("messages", [])
            if not messages:
                return "[GMAIL RESULT] No emails found."
            
            results = []
            for msg in messages[:max_results]:
                msg_id = msg["id"]
                detail_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
                detail_req = urllib.request.Request(
                    detail_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                try:
                    with urllib.request.urlopen(detail_req, timeout=5) as detail_resp:
                        detail_data = json.loads(detail_resp.read().decode())
                        snippet = detail_data.get("snippet", "")
                        headers = detail_data.get("payload", {}).get("headers", [])
                        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(No Subject)")
                        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown Sender")
                        results.append(f"- ID: {msg_id}\n  From: {sender}\n  Subject: {subject}\n  Snippet: {snippet}")
                except Exception:
                    results.append(f"- ID: {msg_id} (Failed to fetch details)")
            return "[GMAIL RESULT] Found messages:\n" + "\n".join(results)
    except Exception as e:
        return f"[GMAIL ERROR] Failed to list messages: {e}"

def gmail_get_message_api(access_token: str, message_id: str) -> str:
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            snippet = data.get("snippet", "")
            headers = data.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(No Subject)")
            sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown Sender")
            date = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
            
            body = ""
            payload = data.get("payload", {})
            parts = payload.get("parts", [])
            if parts:
                for part in parts:
                    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                        import base64
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(errors="ignore")
                        break
            else:
                body_data = payload.get("body", {}).get("data", "")
                if body_data:
                    import base64
                    body = base64.urlsafe_b64decode(body_data).decode(errors="ignore")
            
            if not body:
                body = snippet
                
            return f"[GMAIL RESULT] Message details:\nID: {message_id}\nFrom: {sender}\nDate: {date}\nSubject: {subject}\nBody:\n{body}"
    except Exception as e:
        return f"[GMAIL ERROR] Failed to get message details: {e}"

def gmail_send_message_api(access_token: str, to: str, subject: str, body: str) -> str:
    try:
        import base64
        from email.mime.text import MIMEText
        
        mime_msg = MIMEText(body)
        mime_msg["to"] = to
        mime_msg["subject"] = subject
        raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        req = urllib.request.Request(
            url,
            data=json.dumps({"raw": raw_msg}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode())
            return f"[GMAIL SUCCESS] Message sent. ID: {res_data.get('id')}"
    except Exception as e:
        return f"[GMAIL ERROR] Failed to send message: {e}"

def gdocs_create_doc_api(access_token: str, title: str, initial_text: str = "") -> str:
    try:
        create_url = "https://docs.googleapis.com/v1/documents"
        req = urllib.request.Request(
            create_url,
            data=json.dumps({"title": title}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            doc = json.loads(resp.read().decode())
            doc_id = doc.get("documentId")
            
            if initial_text and doc_id:
                update_data = json.dumps({
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": initial_text
                            }
                        }
                    ]
                }).encode("utf-8")
                up_req = urllib.request.Request(
                    f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                    data=update_data,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(up_req, timeout=10):
                    pass
            return f"[GOOGLE DOCS SUCCESS] Created document '{title}' with ID: {doc_id}"
    except Exception as e:
        return f"[GOOGLE DOCS ERROR] Failed to create document: {e}"

def gdocs_read_doc_api(access_token: str, doc_id: str) -> str:
    try:
        url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            doc = json.loads(resp.read().decode())
            title = doc.get("title", "Untitled")
            
            content_runs = []
            body = doc.get("body", {})
            for element in body.get("content", []):
                p = element.get("paragraph")
                if p:
                    for run in p.get("elements", []):
                        text_run = run.get("textRun")
                        if text_run and text_run.get("content"):
                            content_runs.append(text_run["content"])
            
            full_text = "".join(content_runs)
            return f"[GOOGLE DOCS RESULT] Document Title: {title}\nContent:\n{full_text}"
    except Exception as e:
        return f"[GOOGLE DOCS ERROR] Failed to read document: {e}"

def gdocs_append_text_api(access_token: str, doc_id: str, text: str) -> str:
    try:
        req = urllib.request.Request(
            f"https://docs.googleapis.com/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
            body_content = doc.get("body", {}).get("content", [])
            end_index = 1
            if body_content:
                end_index = body_content[-1].get("endIndex", 1) - 1
                if end_index < 1:
                    end_index = 1
            
            update_data = json.dumps({
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": end_index},
                            "text": text
                        }
                    }
                ]
            }).encode("utf-8")
            up_req = urllib.request.Request(
                f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                data=update_data,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(up_req, timeout=10) as up_resp:
                return f"[GOOGLE DOCS SUCCESS] Appended text to document {doc_id}."
    except Exception as e:
        return f"[GOOGLE DOCS ERROR] Failed to append text to document {doc_id}: {e}"


def find_unclosed_tag(text: str) -> Optional[str]:
    tags = [
        "status", "search", "image_search", "browse_url", "run_command", "run_file", 
        "read_file", "port_check", "http_request", "write_file", "edit_file", 
        "delete_file", "install_package", "agent_terminal", "run_bg_command", 
        "check_process", "capture_view", "view_project_tree", "system_info", 
        "list_processes", "list_directory", "stat_path", "make_directory",
        "copy_file", "move_file", "download_url", "update_roadmap", "replace_file_content",
        "multi_replace_file_content", "configure_google_oauth"
    ]
    pattern = re.compile(r'<(/?)([a-zA-Z_0-9]+)(?:\s+[^>]*|/?)>', re.IGNORECASE)
    stack = []
    for match in pattern.finditer(text):
        is_closing = bool(match.group(1))
        tag_name = match.group(2).lower()
        if tag_name in tags:
            if is_closing:
                if stack and stack[-1] == tag_name:
                    stack.pop()
            else:
                if not match.group(0).endswith("/>"):
                    stack.append(tag_name)
    return stack[-1] if stack else None


def cleanup_terminal_sessions() -> None:
    now = time.time()
    with TERMINAL_SESSIONS_LOCK:
        stale_ids = []
        for session_id, session in TERMINAL_SESSIONS.items():
            too_old = now - session.created_at > TERMINAL_TTL_SECONDS
            finished_and_idle = not session.is_running() and now - session.updated_at > 60
            if too_old or finished_and_idle:
                session.stop()
                stale_ids.append(session_id)
        for session_id in stale_ids:
            TERMINAL_SESSIONS.pop(session_id, None)


def sandbox_execution_needs_correction(run_result: str) -> bool:
    if "INTERACTIVE SCRIPT READY" in run_result or "INTERACTIVE SCRIPT DETECTED" in run_result:
        return False
    if "[AGENT TERMINAL INPUT REQUIRED]" in run_result:
        return True
    
    # Do not retry/correct on Google account config/linking issues since the model cannot self-correct them.
    if "Google account is not linked" in run_result or "sign in with Google" in run_result or "Google credentials are NOT configured" in run_result:
        return False

    lowered = run_result.lower()
    return "ERROR" in run_result or "STDERR" in run_result or "traceback" in lowered or "non-zero exit code" in lowered


def sandbox_feedback_target(run_result: str) -> str:
    file_match = re.search(r"\[RUN FILE RESULT\] Running '([^']+)'", run_result)
    if file_match:
        return f"file `{file_match.group(1)}`"
    cmd_match = re.search(r"\[RUN COMMAND RESULT\] Output of `([^`]+)`", run_result)
    if cmd_match:
        return f"command `{cmd_match.group(1)}`"
    agent_cmd_match = re.search(r"\[AGENT TERMINAL RESULT\] Output of `([^`]+)`", run_result)
    if agent_cmd_match:
        return f"agent terminal command `{agent_cmd_match.group(1)}`"
    input_cmd_match = re.search(r"\[AGENT TERMINAL INPUT REQUIRED\] Command `([^`]+)`", run_result)
    if input_cmd_match:
        return f"agent terminal command `{input_cmd_match.group(1)}`"
    return "workspace code"


def sandbox_feedback_instruction(run_result: str) -> str:
    if "[AGENT TERMINAL INPUT REQUIRED]" in run_result:
        return (
            "The file is interactive and needs stdin for verification. Do not rewrite the program just to avoid EOF. "
            "Rerun the same <agent_terminal> command with a realistic <input>...</input> block and inspect the output."
        )
    if "[AGENT TERMINAL RESULT]" in run_result and "EOFError: EOF when reading a line" in run_result and "--- STDIN PROVIDED ---" not in run_result:
        return (
            "The terminal run failed because no stdin was supplied. Do not change the program just to avoid EOF. "
            "Rerun <agent_terminal> with an <input>...</input> block that exercises the interactive prompts."
        )
    return "Please correct the affected file."


def code_execution_retry_status(feedback_target: str) -> str:
    return (
        "<status>"
        f"Code execution found an issue while running {html.escape(feedback_target)}; "
        "continuing with an automatic fix."
        "</status>"
    )


def python_script_path_from_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return ""
    if not parts:
        return ""
    executable = Path(parts[0]).name.lower()
    if executable not in {"python", "python3", "python3.11", Path(sys.executable).name.lower()}:
        return ""
    for part in parts[1:]:
        if part.endswith(".py"):
            return part
    return ""


def execute_agent_terminal(user_id: int, chat_id: str, command: str, stdin_text: str = "", timeout: int = 20) -> str:
    workspace_dir = workspace_dir_for(user_id, chat_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    command = command.strip()
    if not command:
        return "[AGENT TERMINAL ERROR] No command provided."
    display_command = command

    script_path = python_script_path_from_command(command)
    if script_path and not stdin_text.strip():
        target_path = (workspace_dir / script_path).resolve()
        if path_is_inside(target_path, workspace_dir) and target_path.exists() and target_path.is_file():
            try:
                source = target_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                source = ""
            if source and python_script_uses_input(source):
                escaped_command = html.escape(display_command, quote=True)
                return (
                    f"[AGENT TERMINAL INPUT REQUIRED] Command `{display_command}` targets interactive script "
                    f"'{script_path}', but no <input> block was provided.\n"
                    f"Rerun it like:\n"
                    f"<agent_terminal command=\"{escaped_command}\" timeout=\"20\">\n"
                    f"  <input>sample response 1\nsample response 2\n</input>\n"
                    f"</agent_terminal>"
                )

    command = re.sub(r"^python(\s|$)", shlex.quote(sys.executable) + r"\1", command, count=1)

    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=str(workspace_dir.resolve()),
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 60)),
        )
        output = ""
        if stdin_text:
            output += f"--- STDIN PROVIDED ---\n{stdin_text}\n"
        if res.stdout:
            output += res.stdout
        if res.stderr:
            output += "\n--- STDERR / TRACEBACK ---\n" + res.stderr
        if res.returncode != 0:
            output += f"\nProcess exited with non-zero exit code: {res.returncode}"
        return f"[AGENT TERMINAL RESULT] Output of `{display_command}`:\n{output if output else 'Command completed successfully with empty output.'}"
    except subprocess.TimeoutExpired as exc:
        stdout_before = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode(errors="ignore") if exc.stdout else "")
        stderr_before = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode(errors="ignore") if exc.stderr else "")
        return (
            f"[AGENT TERMINAL ERROR] Command timed out while running `{display_command}`. "
            f"If the program is waiting for input, rerun it with an <input>...</input> block containing the needed keystrokes.\n"
            f"Output before timeout:\n{stdout_before}\n{stderr_before}"
        )
    except Exception as exc:
        return f"[AGENT TERMINAL ERROR] Failed to run `{display_command}`: {exc}"


def execute_sandbox_code(user_id: int, chat_id: str, filename: str) -> str:
    workspace_dir = workspace_dir_for(user_id, chat_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Resolve target path and verify sandbox boundaries
    target_path = (workspace_dir / filename).resolve()
    if not path_is_inside(target_path, workspace_dir):
        return "ERROR: Sandbox Escape Attempt Detected. You cannot access files outside your workspace."

    if not target_path.exists():
        return f"ERROR: File '{filename}' does not exist."

    try:
        if filename.endswith(".py"):
            syntax_ok, code_content, syntax_error = read_python_source_for_check(target_path, filename)
            if not syntax_ok:
                return syntax_error

            if python_script_uses_input(code_content):
                return (
                    f"INTERACTIVE SCRIPT READY: The script '{filename}' uses input(), so it was syntax-checked "
                    f"instead of being run to completion without a user.\n"
                    f"The user can run it in the terminal widget below and type responses there.\n"
                    f"{terminal_tag_for(filename)}"
                )

            try:
                # Execute python script securely in subprocess with a 10s timeout
                res = subprocess.run(
                    [sys.executable, str(target_path)],
                    cwd=str(workspace_dir.resolve()),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = ""
                if res.stdout:
                    output += res.stdout
                if res.stderr:
                    output += "\n--- STDERR / TRACEBACK ---\n" + res.stderr
                if res.returncode != 0:
                    output += f"\nProcess exited with non-zero exit code: {res.returncode}"
                return output if output else "Process completed successfully with empty output."
            except subprocess.TimeoutExpired as te:
                # Check if the script is interactive (contains "input(")
                if python_script_uses_input(code_content):
                    stdout_before = te.stdout if isinstance(te.stdout, str) else (te.stdout.decode(errors="ignore") if te.stdout else "")
                    stderr_before = te.stderr if isinstance(te.stderr, str) else (te.stderr.decode(errors="ignore") if te.stderr else "")
                    msg = (
                        f"INTERACTIVE SCRIPT DETECTED: The script '{filename}' successfully started but is paused waiting for user input.\n"
                        f"Background syntax and initial execution successfully verified. Run it in the terminal widget to provide input.\n"
                        f"{terminal_tag_for(filename)}\n"
                    )
                    if stdout_before:
                        msg += f"\nOutput before pause:\n{stdout_before}"
                    if stderr_before:
                        msg += f"\nDiagnostic output before pause:\n{stderr_before}"
                    return msg
                else:
                    return f"ERROR running script: Process timed out after 10 seconds. Output before timeout:\n{te.stdout.decode(errors='ignore') if te.stdout else ''}\n{te.stderr.decode(errors='ignore') if te.stderr else ''}"
        else:
            return f"File '{filename}' written to workspace. Direct execution not supported for non-python files (only .py scripts can be executed directly). HTML/JS/CSS files can be viewed and downloaded."
    except Exception as e:
        return f"ERROR running script: {str(e)}"


def process_sandbox_tags(user_id: int, chat_id: str, text: str, on_status_update=None) -> Optional[str]:
    file_attr = r'\b(?:filename|file|path)="([^"]+)"'
    write_pattern = re.compile(rf'<write_file\b[^>]*{file_attr}[^>]*>([\s\S]*?)</write_file>', re.IGNORECASE)
    delete_pattern = re.compile(rf'<delete_file\b[^>]*{file_attr}[^>]*/?>|<delete_file\b[^>]*{file_attr}[^>]*></delete_file>|<delete_file>([^<]+)</delete_file>', re.IGNORECASE)
    run_pattern = re.compile(rf'<run_file\b[^>]*{file_attr}[^>]*/?>|<run_file\b[^>]*{file_attr}[^>]*></run_file>|<run_file>([^<]+)</run_file>', re.IGNORECASE)
    read_pattern = re.compile(rf'<read_file\b[^>]*{file_attr}[^>]*/?>|<read_file\b[^>]*{file_attr}[^>]*></read_file>|<read_file>([^<]+)</read_file>|<read_file\b[^>]*{file_attr}[^>]*>([^<]+)</read_file>', re.IGNORECASE)
    run_cmd_pattern = re.compile(r'<run_command>([\s\S]*?)</run_command>|<run_command\s+command="([^"]+)"\s*/?>', re.IGNORECASE)
    edit_pattern = re.compile(rf'<edit_file\b[^>]*{file_attr}[^>]*>([\s\S]*?)</edit_file>', re.IGNORECASE)
    agent_terminal_pattern = re.compile(r'<agent_terminal\s+command="([^"]+)"(?:\s+timeout="(\d+)")?\s*>([\s\S]*?)</agent_terminal>|<agent_terminal\s+command="([^"]+)"(?:\s+timeout="(\d+)")?\s*/?>', re.IGNORECASE)
    tree_pattern = re.compile(r'<view_project_tree\b[^>]*/?>|<view_project_tree\b[^>]*>[\s\S]*?</view_project_tree>', re.IGNORECASE)
    search_pattern = re.compile(r'<search>([\s\S]*?)</search>|<search\s+query="([^"]+)"\s*/?>|call:search\s*\{\s*query:\s*([^}]+)\s*\}', re.IGNORECASE)
    browse_pattern = re.compile(r'<browse_url\s+url="([^"]+)"\s*/?>|<browse_url\s+url="([^"]+)"\s*></browse_url>', re.IGNORECASE)
    list_dir_pattern = re.compile(r'<list_directory(?:\s+path="([^"]*)")?\s*/?>|<list_directory(?:\s+path="([^"]*)")?\s*></list_directory>', re.IGNORECASE)
    stat_path_pattern = re.compile(r'<stat_path\s+path="([^"]+)"\s*/?>|<stat_path\s+path="([^"]+)"\s*></stat_path>', re.IGNORECASE)
    mkdir_pattern = re.compile(r'<make_directory\s+path="([^"]+)"\s*/?>|<make_directory\s+path="([^"]+)"\s*></make_directory>', re.IGNORECASE)
    copy_pattern = re.compile(r'<copy_file\s+from="([^"]+)"\s+to="([^"]+)"\s*/?>|<copy_file\s+from="([^"]+)"\s+to="([^"]+)"\s*></copy_file>', re.IGNORECASE)
    move_pattern = re.compile(r'<move_file\s+from="([^"]+)"\s+to="([^"]+)"\s*/?>|<move_file\s+from="([^"]+)"\s+to="([^"]+)"\s*></move_file>', re.IGNORECASE)
    download_pattern = re.compile(r'<download_url\s+url="([^"]+)"\s+file="([^"]+)"\s*/?>|<download_url\s+url="([^"]+)"\s+file="([^"]+)"\s*></download_url>', re.IGNORECASE)
    capture_pattern = re.compile(r'<capture_view\s+url="([^"]+)"\s+file="([^"]+)"\s*/?>|<capture_view\s+url="([^"]+)"\s+file="([^"]+)"\s*></capture_view>', re.IGNORECASE)
    run_bg_pattern = re.compile(r'<run_bg_command>([\s\S]*?)</run_bg_command>|<run_bg_command\s+command="([^"]+)"\s*/?>', re.IGNORECASE)
    check_process_pattern = re.compile(r'<check_process\s+pid="([^"]+)"\s*/?>|<check_process\s+pid="([^"]+)"\s*></check_process>', re.IGNORECASE)
    kill_process_pattern = re.compile(r'<kill_process\s+pid="([^"]+)"\s*/?>|<kill_process\s+pid="([^"]+)"\s*></kill_process>', re.IGNORECASE)
    roadmap_pattern = re.compile(r'<update_roadmap>([\s\S]*?)</update_roadmap>', re.IGNORECASE)
    install_pattern = re.compile(r'<install_package\s+name="([^"]+)"(?:\s+type="([^"]+)")?\s*/?>|<install_package\s+name="([^"]+)"(?:\s+type="([^"]+)")?></install_package>|<install_package>([^<]+)</install_package>', re.IGNORECASE)
    system_info_pattern = re.compile(r'<system_info\s*/?>|<system_info\s*></system_info>', re.IGNORECASE)
    list_processes_pattern = re.compile(r'<list_processes\s*/?>|<list_processes\s*></list_processes>', re.IGNORECASE)
    port_check_pattern = re.compile(r'<port_check\s+port="(\d+)"(?:\s+host="([^"]+)")?\s*/?>|<port_check\s+host="([^"]+)"\s+port="(\d+)"\s*/?>', re.IGNORECASE)
    http_request_pattern = re.compile(r'<http_request\s+url="([^"]+)"(?:\s+method="([^"]+)")?\s*>([\s\S]*?)</http_request>|<http_request\s+url="([^"]+)"(?:\s+method="([^"]+)")?\s*/?>', re.IGNORECASE)

    gmail_list_pattern = re.compile(r'<gmail_list_messages(?:\s+q="([^"]*)")?(?:\s+max="(\d+)")?\s*/?>|<gmail_list_messages(?:\s+q="([^"]*)")?(?:\s+max="(\d+)")?>([\s\S]*?)</gmail_list_messages>', re.IGNORECASE)
    gmail_get_pattern = re.compile(r'<gmail_get_message\s+id="([^"]+)"\s*/?>|<gmail_get_message\s+id="([^"]+)"\s*></gmail_get_message>', re.IGNORECASE)
    gmail_send_pattern = re.compile(r'<gmail_send_message\s+to="([^"]+)"\s+subject="([^"]+)"\s*>([\s\S]*?)</gmail_send_message>', re.IGNORECASE)
    gdocs_create_pattern = re.compile(r'<gdocs_create_doc\s+title="([^"]+)"\s*>([\s\S]*?)</gdocs_create_doc>', re.IGNORECASE)
    gdocs_read_pattern = re.compile(r'<gdocs_read_doc\s+id="([^"]+)"\s*/?>|<gdocs_read_doc\s+id="([^"]+)"\s*></gdocs_read_doc>', re.IGNORECASE)
    gdocs_append_pattern = re.compile(r'<gdocs_append_text\s+id="([^"]+)"\s*>([\s\S]*?)</gdocs_append_text>', re.IGNORECASE)

    google_config_pattern = re.compile(r'<configure_google_oauth\s+client_id="([^"]+)"\s+client_secret="([^"]+)"\s*/?>|<configure_google_oauth\s+client_id="([^"]+)"\s+client_secret="([^"]+)"\s*></configure_google_oauth>', re.IGNORECASE)
    google_config_json_pattern = re.compile(r'<configure_google_oauth>([\s\S]*?)</configure_google_oauth>', re.IGNORECASE)

    workspace_dir = workspace_dir_for(user_id, chat_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    feedback = []

    # 0. Process explicit web searches in agent/workspace mode
    for match in search_pattern.finditer(text):
        query = next((g for g in match.groups() if g is not None), "").strip()
        if (query.startswith('"') and query.endswith('"')) or (query.startswith("'") and query.endswith("'")):
            query = query[1:-1].strip()
        if query:
            if on_status_update:
                on_status_update(f"Searching web: {query}")
            results = search_duckduckgo(html.unescape(query), max_results=5)
            if results:
                lines = [
                    f"- {item.get('title', '').strip()} ({item.get('url', '').strip()})\n  {item.get('snippet', '').strip()}"
                    for item in results
                ]
                feedback.append(f"[WEB SEARCH RESULTS] {query}\n" + "\n".join(lines))
            else:
                feedback.append(f"[WEB SEARCH RESULTS] {query}\nNo results found.")

    # 0.5. Workspace path management tools
    for match in mkdir_pattern.finditer(text):
        rel = match.group(1) or match.group(2)
        if rel:
            if on_status_update:
                on_status_update(f"Creating directory: {rel}")
            try:
                target = workspace_resolve(workspace_dir, html.unescape(rel.strip()))
                target.mkdir(parents=True, exist_ok=True)
                feedback.append(f"[MAKE DIRECTORY SUCCESS] Created directory '{rel}'.")
            except Exception as exc:
                feedback.append(f"[MAKE DIRECTORY ERROR] Failed to create '{rel}': {exc}")

    for match in list_dir_pattern.finditer(text):
        rel = match.group(1) or match.group(2) or "."
        if on_status_update:
            on_status_update(f"Listing directory: {rel}")
        feedback.append(list_directory_tool(workspace_dir, html.unescape(rel.strip() or ".")))

    for match in stat_path_pattern.finditer(text):
        rel = match.group(1) or match.group(2)
        if rel:
            if on_status_update:
                on_status_update(f"Inspecting path metadata: {rel}")
            feedback.append(stat_path_tool(workspace_dir, html.unescape(rel.strip())))

    for match in copy_pattern.finditer(text):
        src = match.group(1) or match.group(3)
        dst = match.group(2) or match.group(4)
        if src and dst:
            if on_status_update:
                on_status_update(f"Copying {src} to {dst}")
            try:
                source = workspace_resolve(workspace_dir, html.unescape(src.strip()))
                target = workspace_resolve(workspace_dir, html.unescape(dst.strip()))
                if not source.exists() or not source.is_file():
                    feedback.append(f"[COPY FILE ERROR] Source file does not exist: {src}")
                    continue
                old_text = _safe_text_snapshot(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                new_text = _safe_text_snapshot(target)
                record_workspace_diff(workspace_dir, dst, old_text, new_text, "modified" if old_text else "added")
                feedback.append(f"[COPY FILE SUCCESS] Copied '{src}' to '{dst}'.")
            except Exception as exc:
                feedback.append(f"[COPY FILE ERROR] Failed copying '{src}' to '{dst}': {exc}")

    for match in move_pattern.finditer(text):
        src = match.group(1) or match.group(3)
        dst = match.group(2) or match.group(4)
        if src and dst:
            if on_status_update:
                on_status_update(f"Moving {src} to {dst}")
            try:
                source = workspace_resolve(workspace_dir, html.unescape(src.strip()))
                target = workspace_resolve(workspace_dir, html.unescape(dst.strip()))
                if not source.exists():
                    feedback.append(f"[MOVE FILE ERROR] Source path does not exist: {src}")
                    continue
                old_source_text = _safe_text_snapshot(source)
                old_target_text = _safe_text_snapshot(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                new_target_text = _safe_text_snapshot(target)
                if old_source_text:
                    record_workspace_diff(workspace_dir, src, old_source_text, "", "deleted")
                if new_target_text or old_target_text:
                    record_workspace_diff(workspace_dir, dst, old_target_text, new_target_text, "modified" if old_target_text else "added")
                feedback.append(f"[MOVE FILE SUCCESS] Moved '{src}' to '{dst}'.")
            except Exception as exc:
                feedback.append(f"[MOVE FILE ERROR] Failed moving '{src}' to '{dst}': {exc}")

    for match in download_pattern.finditer(text):
        url = match.group(1) or match.group(3)
        filename = match.group(2) or match.group(4)
        if url and filename:
            if on_status_update:
                on_status_update(f"Downloading URL into workspace: {url}")
            feedback.append(download_url_to_workspace(workspace_dir, html.unescape(url.strip()), html.unescape(filename.strip())))

    # 1. Process deletions
    for match in delete_pattern.finditer(text):
        fn = next((g for g in match.groups() if g), "").strip()
        if fn:
            if on_status_update:
                on_status_update(f"Deleting file: {fn}")
            target_path = (workspace_dir / fn).resolve()
            if not path_is_inside(target_path, workspace_dir):
                feedback.append(f"[DELETE FILE ERROR] Sandbox Escape Attempt Detected: {fn}")
                continue
            if target_path.exists():
                try:
                    old_text = _safe_text_snapshot(target_path)
                    if target_path.is_file():
                        target_path.unlink()
                    elif target_path.is_dir():
                        shutil.rmtree(target_path)
                    if old_text:
                        record_workspace_diff(workspace_dir, fn, old_text, "", "deleted")
                    feedback.append(f"[DELETE FILE SUCCESS] Deleted '{fn}'")
                except Exception as e:
                    feedback.append(f"[DELETE FILE ERROR] Failed to delete '{fn}': {str(e)}")
            else:
                feedback.append(f"[DELETE FILE ERROR] Path '{fn}' does not exist.")

    # 2. Process writes
    for match in write_pattern.finditer(text):
        fn = match.group(1)
        content = match.group(2)
        if fn:
            if on_status_update:
                on_status_update(f"Writing file: {fn}")
            target_path = (workspace_dir / fn).resolve()
            if not path_is_inside(target_path, workspace_dir):
                feedback.append(f"[WRITE FILE ERROR] Sandbox Escape Attempt Detected: {fn}")
                continue
            try:
                old_text = _safe_text_snapshot(target_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                record_workspace_diff(workspace_dir, fn, old_text, content, "modified" if old_text else "added")
                feedback.append(f"[WRITE FILE SUCCESS] Wrote/created file '{fn}' ({len(content)} characters)")
            except Exception as e:
                feedback.append(f"[WRITE FILE ERROR] Failed to write file '{fn}': {str(e)}")

    # 3. Process reads
    for match in read_pattern.finditer(text):
        fn = next((g for g in match.groups() if g), "").strip()
        if fn:
            if on_status_update:
                on_status_update(f"Reading file: {fn}")
            target_path = (workspace_dir / fn).resolve()
            if not path_is_inside(target_path, workspace_dir):
                feedback.append(f"[READ FILE ERROR] Sandbox Escape Attempt Detected: {fn}")
                continue
            if target_path.exists() and target_path.is_file():
                try:
                    content = target_path.read_text(encoding="utf-8", errors="ignore")
                    feedback.append(f"[READ FILE SUCCESS] Content of '{fn}':\n```\n{content}\n```")
                except Exception as e:
                    feedback.append(f"[READ FILE ERROR] Failed to read '{fn}': {str(e)}")
            else:
                feedback.append(f"[READ FILE ERROR] File '{fn}' does not exist or is a directory.")

    # 4. Process line-by-line editing
    for match in edit_pattern.finditer(text):
        fn = match.group(1)
        operations_text = match.group(2)
        if fn:
            if on_status_update:
                on_status_update(f"Editing file: {fn}")
            target_path = (workspace_dir / fn).resolve()
            if not path_is_inside(target_path, workspace_dir):
                feedback.append(f"[EDIT FILE ERROR] Sandbox Escape Attempt Detected: {fn}")
                continue
            if not target_path.exists() or not target_path.is_file():
                feedback.append(f"[EDIT FILE ERROR] File '{fn}' does not exist.")
                continue

            try:
                old_text = target_path.read_text(encoding="utf-8", errors="ignore")
                lines = old_text.splitlines()
                op_pattern = re.compile(
                    r'<insert\s+line="(\d+)">([\s\S]*?)</insert>|'
                    r'<delete\s+line="(\d+)"\s*/?>|'
                    r'<delete\s+start="(\d+)"\s+end="(\d+)"\s*/?>|'
                    r'<replace\s+line="(\d+)">([\s\S]*?)</replace>',
                    re.IGNORECASE
                )

                ops = []
                for op_match in op_pattern.finditer(operations_text):
                    g = op_match.groups()
                    if g[0] is not None:  # insert
                        ops.append({"type": "insert", "line": int(g[0]), "content": g[1]})
                    elif g[2] is not None:  # delete single line
                        ops.append({"type": "delete", "line": int(g[2])})
                    elif g[3] is not None:  # delete range
                        ops.append({"type": "delete_range", "start": int(g[3]), "end": int(g[4])})
                    elif g[5] is not None:  # replace
                        ops.append({"type": "replace", "line": int(g[5]), "content": g[6]})

                def get_sort_key(op):
                    if op["type"] == "insert":
                        return op["line"]
                    elif op["type"] == "delete":
                        return op["line"]
                    elif op["type"] == "delete_range":
                        return op["start"]
                    elif op["type"] == "replace":
                        return op["line"]
                    return 0

                ops.sort(key=get_sort_key, reverse=True)

                applied_ops = 0
                for op in ops:
                    if op["type"] == "insert":
                        idx = op["line"] - 1
                        val = op["content"]
                        if idx >= len(lines):
                            lines.append(val)
                        elif idx < 0:
                            lines.insert(0, val)
                        else:
                            lines.insert(idx, val)
                        applied_ops += 1
                    elif op["type"] == "delete":
                        idx = op["line"] - 1
                        if 0 <= idx < len(lines):
                            lines.pop(idx)
                            applied_ops += 1
                    elif op["type"] == "delete_range":
                        start_idx = op["start"] - 1
                        end_idx = op["end"] - 1
                        if 0 <= start_idx <= end_idx < len(lines):
                            del lines[start_idx:end_idx + 1]
                            applied_ops += (end_idx - start_idx + 1)
                    elif op["type"] == "replace":
                        idx = op["line"] - 1
                        val = op["content"]
                        if 0 <= idx < len(lines):
                            lines[idx] = val
                            applied_ops += 1

                target_path.write_text("\n".join(lines), encoding="utf-8")
                record_workspace_diff(workspace_dir, fn, old_text, "\n".join(lines), "modified")
                feedback.append(f"[EDIT FILE SUCCESS] Successfully applied {applied_ops} edits to '{fn}'")
            except Exception as e:
                feedback.append(f"[EDIT FILE ERROR] Failed to edit '{fn}': {str(e)}")

    # 5. Process runs
    for match in run_pattern.finditer(text):
        fn = next((g for g in match.groups() if g), "").strip()
        if fn:
            if on_status_update:
                on_status_update(f"Running file: {fn}")
            run_result = execute_sandbox_code(user_id, chat_id, fn)
            feedback.append(append_error_search_context(f"[RUN FILE RESULT] Running '{fn}':\n{run_result}"))

    # 6. Process shell command runs
    for match in run_cmd_pattern.finditer(text):
        cmd = match.group(1) or match.group(2)
        if cmd:
            cmd = cmd.strip()
            if on_status_update:
                on_status_update(f"Running command: {cmd.splitlines()[0] if cmd else ''}")
            if ".." in cmd or ("/" in cmd and not cmd.startswith(".") and any(part.startswith("..") for part in cmd.split())):
                feedback.append(f"[RUN COMMAND ERROR] Sandbox escape path traversal attempt detected in command: {cmd}")
                continue

            try:
                display_cmd, executable_cmd = normalize_python_command(html.unescape(cmd))
                res = subprocess.run(
                    executable_cmd,
                    shell=True,
                    cwd=str(workspace_dir.resolve()),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = ""
                if res.stdout:
                    output += res.stdout
                if res.stderr:
                    output += "\n--- STDERR / TRACEBACK ---\n" + res.stderr
                if res.returncode != 0:
                    output += f"\nProcess exited with non-zero exit code: {res.returncode}"

                feedback.append(append_error_search_context(f"[RUN COMMAND RESULT] Output of `{display_cmd}`:\n{output if output else 'Command completed successfully with empty output.'}"))
            except Exception as e:
                feedback.append(append_error_search_context(f"[RUN COMMAND ERROR] Failed to run command `{cmd}`: {str(e)}"))

    # 7. Process agent terminal runs with optional stdin
    for match in agent_terminal_pattern.finditer(text):
        command = match.group(1) or match.group(4)
        timeout_raw = match.group(2) or match.group(5)
        body = match.group(3) or ""
        stdin_match = re.search(r'<input>([\s\S]*?)</input>', body, re.IGNORECASE)
        stdin_text = html.unescape(stdin_match.group(1)) if stdin_match else ""
        timeout = int(timeout_raw) if timeout_raw else 20
        if command:
            if on_status_update:
                on_status_update(f"Running interactive terminal: {command}")
            feedback.append(append_error_search_context(execute_agent_terminal(user_id, chat_id, html.unescape(command), stdin_text, timeout)))

    # 8. Project tree
    if tree_pattern.search(text):
        if on_status_update:
            on_status_update("Inspecting project folder layout")
        feedback.append(f"[PROJECT TREE]\n{workspace_tree(workspace_dir)}")

    # 9. Browse URLs into text context
    for match in browse_pattern.finditer(text):
        url = match.group(1) or match.group(2)
        if url:
            if on_status_update:
                on_status_update(f"Browsing URL: {url}")
            feedback.append(browse_url_text(html.unescape(url.strip())))

    # 10. Background process lifecycle
    for match in run_bg_pattern.finditer(text):
        cmd = (match.group(1) or match.group(2) or "").strip()
        if cmd:
            if on_status_update:
                on_status_update(f"Starting background app: {cmd}")
            feedback.append(start_background_process(user_id, chat_id, html.unescape(cmd)))

    for match in check_process_pattern.finditer(text):
        pid = match.group(1) or match.group(2)
        if pid:
            if on_status_update:
                on_status_update(f"Checking background process status: {pid}")
            feedback.append(append_error_search_context(check_background_process(user_id, chat_id, pid.strip())))

    for match in capture_pattern.finditer(text):
        url = match.group(1) or match.group(3)
        filename = match.group(2) or match.group(4)
        if url and filename:
            if on_status_update:
                on_status_update(f"Capturing screenshot of: {url}")
            feedback.append(capture_view(user_id, chat_id, html.unescape(url.strip()), html.unescape(filename.strip())))

    for match in kill_process_pattern.finditer(text):
        pid = match.group(1) or match.group(2)
        if pid:
            if on_status_update:
                on_status_update(f"Stopping background process: {pid}")
            feedback.append(kill_background_process(user_id, chat_id, pid.strip()))

    # 11. Persistent roadmap updates
    for match in roadmap_pattern.finditer(text):
        if on_status_update:
            on_status_update("Updating project roadmap checklist")
        feedback.append(update_roadmap_file(workspace_dir, html.unescape(match.group(1))))

    # 12. Process package installations
    for match in install_pattern.finditer(text):
        name = match.group(1) or match.group(3) or match.group(5)
        pkg_type = match.group(2) or match.group(4) or "pip"
        name = name.strip() if name else ""
        if name:
            if on_status_update:
                on_status_update(f"Installing package '{name}' via {pkg_type}")
            feedback.append(f"[INSTALL PACKAGE] Installing '{name}' via {pkg_type}...")
            try:
                if pkg_type.lower() == "npm":
                    package_json = workspace_dir / "package.json"
                    if not package_json.exists():
                        subprocess.run("npm init -y", shell=True, cwd=str(workspace_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    res = subprocess.run(f"npm install {name}", shell=True, cwd=str(workspace_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
                else:
                    res = subprocess.run(f"python3 -m pip install {name}", shell=True, cwd=str(workspace_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

                if res.returncode == 0:
                    feedback.append(f"[INSTALL PACKAGE SUCCESS] Successfully installed '{name}'")
                else:
                    feedback.append(f"[INSTALL PACKAGE ERROR] Failed to install '{name}': {res.stderr}")
            except Exception as e:
                feedback.append(f"[INSTALL PACKAGE ERROR] Error installing '{name}': {str(e)}")

    # 13. Owned computer inspection and HTTP tools
    if system_info_pattern.search(text):
        if on_status_update:
            on_status_update("Inspecting owned computer system info")
        feedback.append(owned_system_info())

    if list_processes_pattern.search(text):
        if on_status_update:
            on_status_update("Listing owned computer processes")
        feedback.append(list_owned_processes(user_id, chat_id))

    for match in port_check_pattern.finditer(text):
        port = match.group(1) or match.group(4)
        host = match.group(2) or match.group(3) or "127.0.0.1"
        if on_status_update:
            on_status_update(f"Checking port {host}:{port}")
        feedback.append(check_port(html.unescape(host), port))

    for match in http_request_pattern.finditer(text):
        url = match.group(1) or match.group(4)
        method = match.group(2) or match.group(5) or "GET"
        body = match.group(3) or ""
        if url:
            if on_status_update:
                on_status_update(f"Making HTTP request: {method.upper()} {url}")
            feedback.append(http_request_tool(html.unescape(url.strip()), method, html.unescape(body.strip())))

    # 15. Gmail tools
    google_token = get_google_credentials(str(user_id))

    for match in gmail_list_pattern.finditer(text):
        if not google_token:
            feedback.append("[GMAIL ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        g = match.groups()
        q = g[0] or g[2] or g[4] or ""
        max_res = int(g[1] or g[3] or "10")
        if on_status_update:
            on_status_update(f"Searching Gmail: {q}")
        feedback.append(gmail_list_messages_api(google_token, q.strip(), max_res))

    for match in gmail_get_pattern.finditer(text):
        if not google_token:
            feedback.append("[GMAIL ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        msg_id = match.group(1) or match.group(2)
        if msg_id:
            if on_status_update:
                on_status_update(f"Reading email: {msg_id}")
            feedback.append(gmail_get_message_api(google_token, msg_id.strip()))

    for match in gmail_send_pattern.finditer(text):
        if not google_token:
            feedback.append("[GMAIL ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        to = match.group(1)
        subject = match.group(2)
        body = match.group(3) or ""
        if to and subject:
            if on_status_update:
                on_status_update(f"Sending email to: {to}")
            feedback.append(gmail_send_message_api(google_token, to.strip(), html.unescape(subject.strip()), html.unescape(body.strip())))

    # 16. Google Docs tools
    for match in gdocs_create_pattern.finditer(text):
        if not google_token:
            feedback.append("[GOOGLE DOCS ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        title = match.group(1)
        content = match.group(2) or ""
        if title:
            if on_status_update:
                on_status_update(f"Creating Google Doc: {title}")
            feedback.append(gdocs_create_doc_api(google_token, html.unescape(title.strip()), html.unescape(content.strip())))

    for match in gdocs_read_pattern.finditer(text):
        if not google_token:
            feedback.append("[GOOGLE DOCS ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        doc_id = match.group(1) or match.group(2)
        if doc_id:
            if on_status_update:
                on_status_update(f"Reading Google Doc: {doc_id}")
            feedback.append(gdocs_read_doc_api(google_token, doc_id.strip()))

    for match in gdocs_append_pattern.finditer(text):
        if not google_token:
            feedback.append("[GOOGLE DOCS ERROR] Google account is not linked. Please sign in with Google in Settings.")
            continue
        doc_id = match.group(1)
        content = match.group(2) or ""
        if doc_id:
            if on_status_update:
                on_status_update(f"Updating Google Doc: {doc_id}")
            feedback.append(gdocs_append_text_api(google_token, doc_id.strip(), html.unescape(content.strip())))

    for match in google_config_pattern.finditer(text):
        client_id = match.group(1) or match.group(3)
        client_secret = match.group(2) or match.group(4)
        if client_id and client_secret:
            try:
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE IF NOT EXISTS google_config (key TEXT PRIMARY KEY, value TEXT)")
                cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_id', ?)", (client_id.strip(),))
                cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_secret', ?)", (client_secret.strip(),))
                conn.commit()
                conn.close()
                feedback.append("[GOOGLE CONFIG SUCCESS] Google Client ID and Secret have been configured successfully!")
            except Exception as e:
                feedback.append(f"[GOOGLE CONFIG ERROR] Failed to save Google configuration: {str(e)}")

    for match in google_config_json_pattern.finditer(text):
        json_str = match.group(1).strip()
        try:
            import json as py_json
            parsed = py_json.loads(json_str)
            client_id = None
            client_secret = None
            if isinstance(parsed, dict):
                if "installed" in parsed and isinstance(parsed["installed"], dict):
                    client_id = parsed["installed"].get("client_id")
                    client_secret = parsed["installed"].get("client_secret")
                elif "web" in parsed and isinstance(parsed["web"], dict):
                    client_id = parsed["web"].get("client_id")
                    client_secret = parsed["web"].get("client_secret")
                elif "client_id" in parsed and "client_secret" in parsed:
                    client_id = parsed.get("client_id")
                    client_secret = parsed.get("client_secret")
            
            if client_id and client_secret:
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE IF NOT EXISTS google_config (key TEXT PRIMARY KEY, value TEXT)")
                cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_id', ?)", (client_id.strip(),))
                cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_secret', ?)", (client_secret.strip(),))
                conn.commit()
                conn.close()
                feedback.append("[GOOGLE CONFIG SUCCESS] Google credentials JSON configured successfully!")
            else:
                feedback.append("[GOOGLE CONFIG ERROR] Could not find 'client_id' and 'client_secret' in the provided JSON.")
        except Exception as e:
            feedback.append(f"[GOOGLE CONFIG ERROR] Failed to parse credentials JSON: {str(e)}")

    if feedback:
        return "\n\n".join(feedback)
    return None




try:
    import torch
except Exception:  # pragma: no cover - lightweight fallback for headless/test environments
    torch = None

try:
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, PlainTextResponse
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
except Exception:  # pragma: no cover - optional dependency fallback
    Depends = lambda *args, **kwargs: None

    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:  # type: ignore[override]
        pass

    class status:  # type: ignore[assignment]
        HTTP_200_OK = 200

    class FastAPI:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_middleware(self, *args, **kwargs) -> None:
            return None

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def options(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def on_event(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class CORSMiddleware:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class FileResponse:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class StreamingResponse:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class JSONResponse:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class PlainTextResponse:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class HTTPBasic:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

    class HTTPBasicCredentials:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            pass

from pydantic import BaseModel, Field

try:
    from geocentric.training_metrics import load_training_metrics
except Exception:  # pragma: no cover - optional dependency fallback
    load_training_metrics = lambda *args, **kwargs: {}

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - optional dependency fallback
    Fernet = None

try:
    from geocentric import command_center
except Exception:  # pragma: no cover - optional dependency fallback
    command_center = None

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None

import subprocess

try:
    from geocentric.checkpoint import load_model_and_tokenizer
except Exception:  # pragma: no cover - optional dependency fallback
    load_model_and_tokenizer = None

try:
    from geocentric.device import resolve_dtype, runtime_check, select_device
except Exception:  # pragma: no cover - optional dependency fallback
    resolve_dtype = runtime_check = select_device = None

try:
    from geocentric.generate import build_chat_prompt, generate_text, stream_text, visible_thinking_note, generate_reasoning_steps
except Exception:  # pragma: no cover - optional dependency fallback
    build_chat_prompt = generate_text = stream_text = visible_thinking_note = generate_reasoning_steps = None

from geocentric.tool_runtime import ToolRuntime, classify_status_theme, enforce_tool_claim_guard, render_status_banner


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "geocentric-local"
    messages: List[Message]
    stream: bool = True
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=DEFAULT_CHAT_MAX_TOKENS, ge=1, le=MAX_GENERATION_TOKENS)
    top_k: int = Field(default=50, ge=0, le=500)
    repetition_penalty: float = Field(default=1.15, ge=1.0, le=2.0)
    searchWeb: Optional[bool] = False
    effort: Optional[str] = None


# Models for the custom premium web client interface
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatMessage(BaseModel):
    role: str
    content: str
    attachments: Optional[List[Any]] = None


class WebChatRequest(BaseModel):
    model: str = "geocentric-cloud"
    conversationId: str
    messages: List[ChatMessage]
    stream: bool = True
    account: Optional[Dict[str, Any]] = None
    attachments: Optional[List[Any]] = None
    searchWeb: Optional[bool] = False
    agentMode: Optional[bool] = None
    systemPrompt: Optional[str] = None
    mode: Optional[str] = None
    modelMode: Optional[str] = None
    projectPath: Optional[str] = None
    effort: Optional[str] = None


class AgentJobStartResponse(BaseModel):
    jobId: str
    chatId: str
    status: str
    progress: str
    roadmap: Optional[str] = None


class WorkspaceDiffActionRequest(BaseModel):
    path: str


class TerminalStartRequest(BaseModel):
    filename: str


class TerminalInputRequest(BaseModel):
    input: str = ""


# Secure key generation or loading for AES-256 symmetric encryption
KEY_FILE = "secret.key"
if Fernet is not None:
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()

    cipher_suite = Fernet(key)
else:
    cipher_suite = None


def encrypt_data(data: str) -> str:
    if cipher_suite is None:
        return data
    return cipher_suite.encrypt(data.encode('utf-8')).decode('utf-8')


def decrypt_data(token: str) -> str:
    if cipher_suite is None:
        return token
    return cipher_suite.decrypt(token.encode('utf-8')).decode('utf-8')


# Secure password hashing with PBKDF2 and 100,000 SHA-256 iterations, further protected with AES encryption
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    hash_str = f"{salt.hex()}:{key.hex()}"
    return encrypt_data(hash_str)


def verify_password(stored_password: str, provided_password: str) -> bool:
    try:
        # Try decrypting first (new AES encrypted PBKDF2 format)
        decrypted = decrypt_data(stored_password)
        salt_hex, key_hex = decrypted.split(':')
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
        return new_key == key
    except Exception:
        # Legacy fallback support to prevent breaking existing accounts
        try:
            salt_hex, key_hex = stored_password.split(':')
            salt = bytes.fromhex(salt_hex)
            key = bytes.fromhex(key_hex)
            new_key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
            return new_key == key
        except Exception:
            return False


# Database setup function for secure user persistent storage
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_credentials (
            user_id TEXT PRIMARY KEY,
            google_id TEXT UNIQUE,
            email TEXT,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_expiry REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            messages TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            status TEXT NOT NULL,
            progress TEXT NOT NULL,
            reply TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cron_jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT 'geocentric-local',
            interval_minutes INTEGER NOT NULL DEFAULT 5,
            interval_hours INTEGER NOT NULL DEFAULT 0,
            last_run REAL,
            created_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("PRAGMA table_info(cron_jobs)")
    cron_columns = {row[1] for row in cursor.fetchall()}
    cron_migrations = {
        "prompt": "ALTER TABLE cron_jobs ADD COLUMN prompt TEXT NOT NULL DEFAULT ''",
        "model": "ALTER TABLE cron_jobs ADD COLUMN model TEXT NOT NULL DEFAULT 'geocentric-local'",
        "interval_minutes": "ALTER TABLE cron_jobs ADD COLUMN interval_minutes INTEGER NOT NULL DEFAULT 5",
        "interval_hours": "ALTER TABLE cron_jobs ADD COLUMN interval_hours INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in cron_migrations.items():
        if column not in cron_columns:
            cursor.execute(statement)
    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cursor.fetchall()}
    user_migrations = {
        "is_pro": "ALTER TABLE users ADD COLUMN is_pro INTEGER NOT NULL DEFAULT 0",
        "infinite_usage": "ALTER TABLE users ADD COLUMN infinite_usage INTEGER NOT NULL DEFAULT 0",
        "token_limit": "ALTER TABLE users ADD COLUMN token_limit INTEGER NOT NULL DEFAULT 50000",
        "tokens_used": "ALTER TABLE users ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0",
        "image_limit": "ALTER TABLE users ADD COLUMN image_limit INTEGER NOT NULL DEFAULT 10",
        "images_used": "ALTER TABLE users ADD COLUMN images_used INTEGER NOT NULL DEFAULT 0",
        "limited_until": "ALTER TABLE users ADD COLUMN limited_until REAL NOT NULL DEFAULT 0.0",
    }
    for column, statement in user_migrations.items():
        if column not in user_columns:
            cursor.execute(statement)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# In-memory IP rate limiting to prevent hacking, brute force, and flood/DDoS
class RateLimiter:
    def __init__(self, requests_limit: int, window_seconds: int):
        self.limit = requests_limit
        self.window = window_seconds
        self.history = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        # Periodically prune unused IPs to prevent memory leak/bloat
        if len(self.history) > 1000:
            for k in list(self.history.keys()):
                self.history[k] = [t for t in self.history[k] if now - t < self.window]
                if not self.history[k]:
                    del self.history[k]

        self.history[ip] = [t for t in self.history[ip] if now - t < self.window]
        if len(self.history[ip]) >= self.limit:
            return False
        self.history[ip].append(now)
        return True


global_limiter = RateLimiter(requests_limit=120, window_seconds=60)
auth_limiter = RateLimiter(requests_limit=10, window_seconds=60)


def sse_chunk(content: str, reasoning_content: str = "", usage: Optional[dict[str, Any]] = None) -> str:
    delta = {}
    if content:
        delta["content"] = content
    if reasoning_content:
        delta["reasoning_content"] = reasoning_content
    payload: dict[str, Any] = {"choices": [{"delta": delta}]}
    if usage:
        payload["usage"] = usage
    return f"data: {json.dumps(payload)}\n\n"


def stream_hidden_metadata_chunks(text: str):
    """Emit hidden UI metadata (chat title, trailing status) before stream end."""
    chunks: list[str] = []
    suggested_title = extract_chat_title_tag(text)
    if suggested_title:
        chunks.append(sse_chunk(f"<chat_title>{suggested_title}</chat_title>"))
    _, statuses = extract_status_tags(text)
    if statuses:
        chunks.append(sse_chunk(f"<status>{statuses[-1]}</status>"))
    return chunks


def extract_status_tags(text: str) -> tuple[str, list[str]]:
    statuses = [html.unescape(m.group(1).strip()) for m in re.finditer(r"<status>([\s\S]*?)</status>", text or "", re.IGNORECASE)]
    cleaned = re.sub(r"<status>[\s\S]*?</status>", "", text or "", flags=re.IGNORECASE).strip()
    return cleaned, [s for s in statuses if s]


def extract_usage_payload(payload: Any) -> Optional[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return None
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None
    if not usage:
        return None
    prompt_tokens = usage.get("prompt_tokens") or usage.get("prompt") or usage.get("input_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or usage.get("completion") or usage.get("output_tokens") or 0
    total_tokens = usage.get("total_tokens") or usage.get("total") or ((int(prompt_tokens) if str(prompt_tokens).isdigit() else 0) + (int(completion_tokens) if str(completion_tokens).isdigit() else 0))
    if not isinstance(prompt_tokens, int):
        try:
            prompt_tokens = int(prompt_tokens)
        except Exception:
            prompt_tokens = 0
    if not isinstance(completion_tokens, int):
        try:
            completion_tokens = int(completion_tokens)
        except Exception:
            completion_tokens = 0
    if not isinstance(total_tokens, int):
        try:
            total_tokens = int(total_tokens)
        except Exception:
            total_tokens = prompt_tokens + completion_tokens
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}


def build_usage_payload(prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    total_tokens = prompt_tokens + completion_tokens
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}


def inject_tool_claim_correction(text: str, tool_context: str = "") -> Optional[str]:
    if enforce_tool_claim_guard(text, tool_context):
        return None
    return (
        "[SYSTEM FEEDBACK: Your last response claimed a file or system action but did not include the matching XML tool tag.]\n"
        "Immediately emit the required tool block before continuing, for example <write_file filename=\"file.txt\">content</write_file> or <run_command>ls</run_command>."
    )


def extract_tool_progress_event(text: str) -> str:
    src = text or ""
    tool_patterns: list[tuple[str, str]] = [
        (r'<write_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "Writing file: {value}"),
        (r'<edit_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "Editing file: {value}"),
        (r'<read_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "Reading file: {value}"),
        (r'<delete_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "Deleting file: {value}"),
        (r'<run_file\b[^>]*\b(?:filename|file|path)="([^"]+)"', "Running file: {value}"),
        (r'<agent_terminal\s+command="([^"]+)"', "Testing in terminal: {value}"),
        (r'<run_command(?:\s+command="([^"]+)")?\s*>([\s\S]*?)(?:</run_command>|$)', "Running command: {value}"),
        (r'<run_bg_command(?:\s+command="([^"]+)")?\s*>([\s\S]*?)(?:</run_bg_command>|$)', "Starting background app: {value}"),
        (r'<check_process\s+pid="([^"]+)"', "Checking background process: {value}"),
        (r'<kill_process\s+pid="([^"]+)"', "Stopping background process: {value}"),
        (r'<capture_view\s+url="([^"]+)"', "Capturing browser view: {value}"),
        (r'<browse_url\s+url="([^"]+)"', "Browsing documentation: {value}"),
        (r'<install_package\s+name="([^"]+)"', "Installing package: {value}"),
        (r'<http_request\s+url="([^"]+)"', "Checking URL: {value}"),
        (r'<port_check\b[^>]*port="([^"]+)"', "Checking port: {value}"),
        (r'<view_project_tree\b', "Inspecting project tree"),
        (r'<update_roadmap\b', "Updating roadmap"),
        (r'<system_info\b', "Inspecting system info"),
        (r'<list_processes\b', "Listing running processes"),
    ]
    latest: tuple[int, str] | None = None
    for pattern, label in tool_patterns:
        for match in re.finditer(pattern, src, re.IGNORECASE):
            value = next((group for group in match.groups() if group), "")
            value = html.unescape(value).strip().splitlines()[0] if value else ""
            if len(value) > 90:
                value = value[:87] + "..."
            status = label.format(value=value) if "{value}" in label else label
            if latest is None or match.start() >= latest[0]:
                latest = (match.start(), status)
    return latest[1] if latest else ""


def read_workspace_roadmap(workspace_dir: Path) -> str:
    agents_path = (workspace_dir / "agents.md").resolve()
    if not path_is_inside(agents_path, workspace_dir) or not agents_path.exists():
        return ""
    content = agents_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"## Current Roadmap\s*([\s\S]*?)(?=\n## |\Z)", content, re.IGNORECASE)
    roadmap = match.group(1).strip() if match else ""
    if roadmap.strip() == "- [ ] No active roadmap yet.":
        return ""
    return roadmap


def strip_internal_tags(text: str) -> str:
    src = text or ""
    tag_patterns = [
        r"call:search\s*\{\s*query:\s*[^}]*\}",
        r"<status>[\s\S]*?</status>",
        r"<chat_title\b[^>]*>[\s\S]*?</chat_title>",
        r"<search>[\s\S]*?</search>",
        r"<image_search>[\s\S]*?</image_search>",
        r"\[(?:chat_title|search|image_search)\][\s\S]*?\[/(?:chat_title|search|image_search)\]",
        r"<write_file\b[\s\S]*?</write_file>",
        r"<delete_file\b[\s\S]*?(?:/>|</delete_file>)",
        r"<run_file\b[\s\S]*?(?:/>|</run_file>)",
        r"<run_command\b[^>]*>[\s\S]*?</run_command>",
        r"<run_command\b[\s\S]*?/>",
        r"<agent_terminal\b[\s\S]*?</agent_terminal>",
        r"<read_file\b[\s\S]*?(?:/>|</read_file>)",
        r"<edit_file\b[\s\S]*?</edit_file>",
        r"<insert\b[\s\S]*?</insert>",
        r"<delete\b[\s\S]*?(?:/>|</delete>)",
        r"<replace\b[\s\S]*?</replace>",
        r"<browse_url\b[\s\S]*?(?:/>|</browse_url>)",
        r"<list_directory\b[\s\S]*?(?:/>|</list_directory>)",
        r"<stat_path\b[\s\S]*?(?:/>|</stat_path>)",
        r"<make_directory\b[\s\S]*?(?:/>|</make_directory>)",
        r"<copy_file\b[\s\S]*?(?:/>|</copy_file>)",
        r"<move_file\b[\s\S]*?(?:/>|</move_file>)",
        r"<download_url\b[\s\S]*?(?:/>|</download_url>)",
        r"<capture_view\b[\s\S]*?(?:/>|</capture_view>)",
        r"<run_bg_command\b[\s\S]*?</run_bg_command>",
        r"<run_bg_command\b[\s\S]*?/>",
        r"<check_process\b[\s\S]*?(?:/>|</check_process>)",
        r"<kill_process\b[\s\S]*?(?:/>|</kill_process>)",
        r"<view_project_tree\b[\s\S]*?(?:/>|</view_project_tree>)",
        r"<update_roadmap>[\s\S]*?</update_roadmap>",
        r"<install_package\b[\s\S]*?(?:/>|</install_package>)",
        r"<system_info\b[\s\S]*?(?:/>|</system_info>)",
        r"<list_processes\b[\s\S]*?(?:/>|</list_processes>)",
        r"<port_check\b[\s\S]*?(?:/>|</port_check>)",
        r"<http_request\b[\s\S]*?(?:/>|</http_request>)",
        r"<gmail_list_messages\b[\s\S]*?(?:/>|</gmail_list_messages>)",
        r"<gmail_get_message\b[\s\S]*?(?:/>|</gmail_get_message>)",
        r"<gmail_send_message\b[\s\S]*?</gmail_send_message>",
        r"<gdocs_create_doc\b[\s\S]*?</gdocs_create_doc>",
        r"<gdocs_read_doc\b[\s\S]*?(?:/>|</gdocs_read_doc>)",
        r"<gdocs_append_text\b[\s\S]*?</gdocs_append_text>",
    ]
    for pattern in tag_patterns:
        src = re.sub(pattern, "", src, flags=re.IGNORECASE)

    # Strip completed or partial call:search calls
    src = re.sub(r"call:search\s*\{\s*query:\s*[\s\S]*$", "", src, flags=re.IGNORECASE)

    partial_tags = [
        "chat_title", "search", "image_search", "write_file", "delete_file", "run_file", "run_command",
        "agent_terminal", "read_file", "edit_file", "insert", "delete", "replace",
        "browse_url", "capture_view", "run_bg_command", "check_process", "kill_process",
        "list_directory", "stat_path", "make_directory", "copy_file", "move_file", "download_url",
        "view_project_tree", "update_roadmap", "install_package", "system_info",
        "list_processes", "port_check", "http_request", "status",
        "gmail_list_messages", "gmail_get_message", "gmail_send_message",
        "gdocs_create_doc", "gdocs_read_doc", "gdocs_append_text",
    ]
    for tag in partial_tags:
        if tag in ("write_file", "edit_file", "read_file", "delete_file", "run_file"):
            src = re.sub(rf"<{tag}\b[^>]*$", "", src, flags=re.IGNORECASE)
            src = re.sub(rf"<{tag}\s+[^>]*\b(?:filename|file|path)=[^>]*>[\s\S]*$", "", src, flags=re.IGNORECASE)
        elif tag in ("run_command", "run_bg_command", "agent_terminal", "update_roadmap"):
            src = re.sub(rf"<{tag}\b[^>]*$", "", src, flags=re.IGNORECASE)
            src = re.sub(rf"<{tag}\b[^>]*>\s*\n[\s\S]*$", "", src, flags=re.IGNORECASE)
        else:
            src = re.sub(rf"<{tag}\b[^>]*$", "", src, flags=re.IGNORECASE)
    src = re.sub(
        r"(?im)^\s*\[(?:image|web|real-time|realtime|api|tool|chat\s*title)[^\]\n]{0,80}\]\s*:?\s*",
        "",
        src,
    )
    src = re.sub(r"(?im)^\s*chat\s+title\s*:.*$", "", src)
    src = re.sub(
        r"(?im)^\s*(?:image|web)\s+search(?:\s+tool)?\s*:.*$",
        "",
        src,
    )
    src = re.sub(r"!\[[^\]]*\]\(https?://(?:www\.)?example\.com/[^)]+\)", "", src, flags=re.IGNORECASE)
    src = re.sub(r"\[[^\]]*\]\(https?://(?:www\.)?example\.com/[^)]+\)", "", src, flags=re.IGNORECASE)
    return src.strip()


def strip_agent_progress_notices(text: str) -> str:
    src = text or ""
    notice_patterns = [
        r"\*Code execution found an issue while running [^*]+; asking the model to fix it\.{1,3}\*",
        r"Code execution found an issue while running [^.;\n]+; continuing with an automatic fix\.{1,3}",
        r"\[Workspace Result\]\n[\s\S]*",
    ]
    for pattern in notice_patterns:
        src = re.sub(pattern, "", src, flags=re.IGNORECASE)
    return src.strip()


def finalize_agent_visible_reply(raw_reply: str, user_id: int | str, chat_id: str) -> tuple[str, list[str], str]:
    without_status, statuses = extract_status_tags(raw_reply)
    suggested_title = extract_chat_title_tag(without_status)
    visible = strip_internal_tags(without_status)
    visible = strip_agent_progress_notices(visible)
    if not visible.strip():
        visible = synthesize_completion_reply(user_id, chat_id, statuses)
    return visible.strip(), statuses, suggested_title


def extract_chat_title_tag(text: str) -> str:
    match = re.search(r"<chat_title\b[^>]*>([\s\S]*?)</chat_title>", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return _title_case_topic(re.sub(r"\s+", " ", match.group(1)).strip())[:48]


def workspace_output_summary(user_id: int | str, chat_id: str) -> str:
    workspace_dir = workspace_dir_for(user_id, chat_id)
    if not workspace_dir.exists():
        return "I finished the request, but there are no workspace files to list yet."

    files = []
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules"}
    for path in sorted(workspace_dir.rglob("*"), key=lambda p: str(p).lower()):
        if len(files) >= 14:
            break
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(workspace_dir).parts):
            continue
        rel = path.relative_to(workspace_dir).as_posix()
        if rel.endswith(".md") and rel in {"agents.md", "memory.md", "tools.md", "user.md"}:
            continue
        files.append(rel)

    if not files:
        return "I finished the workspace task. No downloadable project files were created."

    links = [
        f"- [{rel}](/api/download/{urllib.parse.quote(chat_id)}/{urllib.parse.quote(rel, safe='/')})"
        for rel in files
    ]
    extra = "\n\nThere are more files in the workspace too." if len(files) == 14 else ""
    return "I finished the workspace task. Here are the files I produced or updated:\n" + "\n".join(links) + extra


def _line_count_for_change(path: Path) -> int:
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            return 0
        return max(1, len(path.read_text(encoding="utf-8", errors="ignore").splitlines()))
    except Exception:
        return 0


DIFF_STORE_NAME = ".geocentric_diffs.json"


def _safe_text_snapshot(path: Path) -> str:
    try:
        if not path.exists() or not path.is_file() or path.stat().st_size > 240_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _diff_store_path(workspace_dir: Path) -> Path:
    return workspace_dir / DIFF_STORE_NAME


def _read_diff_store(workspace_dir: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_diff_store_path(workspace_dir).read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_diff_store(workspace_dir: Path, items: list[dict[str, Any]]) -> None:
    try:
        _diff_store_path(workspace_dir).write_text(json.dumps(items[-60:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _preview_text(text: str, max_lines: int = 90, max_chars: int = 12_000) -> str:
    clipped = "\n".join((text or "").splitlines()[:max_lines])
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars] + "\n...[truncated]"
    return clipped


def record_workspace_diff(workspace_dir: Path, rel_path: str, old_text: str, new_text: str, status: str = "modified") -> None:
    if old_text == new_text:
        return
    rel = rel_path.strip().strip('"')
    if not rel:
        return
    patch_lines = list(difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        lineterm="",
    ))
    additions = sum(1 for line in patch_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch_lines if line.startswith("-") and not line.startswith("---"))
    item = {
        "path": rel,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "oldContent": old_text[:240_000],
        "newContent": new_text[:240_000],
        "oldPreview": _preview_text(old_text),
        "newPreview": _preview_text(new_text),
        "patch": "\n".join(patch_lines[:220]),
        "approved": False,
        "createdAt": time.time(),
    }
    items = [existing for existing in _read_diff_store(workspace_dir) if existing.get("path") != rel]
    items.append(item)
    _write_diff_store(workspace_dir, items)


def workspace_diff_summary(workspace_dir: Path, max_entries: int = 12) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in reversed(_read_diff_store(workspace_dir)):
        if item.get("approved"):
            continue
        summaries.append({
            "path": item.get("path", ""),
            "status": item.get("status", "modified"),
            "additions": int(item.get("additions") or 0),
            "deletions": int(item.get("deletions") or 0),
            "oldPreview": item.get("oldPreview", ""),
            "newPreview": item.get("newPreview", ""),
            "patch": item.get("patch", ""),
        })
        if len(summaries) >= max_entries:
            break
    return summaries


def set_workspace_diff_approval(workspace_dir: Path, rel_path: str, approved: bool) -> bool:
    changed = False
    items = _read_diff_store(workspace_dir)
    for item in items:
        if item.get("path") == rel_path:
            item["approved"] = approved
            changed = True
    if changed:
        _write_diff_store(workspace_dir, items)
    return changed


def rollback_workspace_diff(workspace_dir: Path, rel_path: str) -> bool:
    items = _read_diff_store(workspace_dir)
    remaining: list[dict[str, Any]] = []
    rolled_back = False
    for item in items:
        if item.get("path") == rel_path:
            target = (workspace_dir / rel_path).resolve()
            if not path_is_inside(target, workspace_dir):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            old_content = item.get("oldContent", "")
            target.write_text(old_content, encoding="utf-8")
            rolled_back = True
        else:
            remaining.append(item)
    if rolled_back:
        _write_diff_store(workspace_dir, remaining)
    return rolled_back


def workspace_change_summary(workspace_dir: Path, max_entries: int = 20) -> list[dict[str, Any]]:
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        return []

    changes: dict[str, dict[str, Any]] = {}

    def record(path_text: str, status: str = "modified", additions: int = 0, deletions: int = 0) -> None:
        clean_path = path_text.strip().strip('"')
        if not clean_path:
            return
        if " -> " in clean_path:
            clean_path = clean_path.split(" -> ", 1)[1].strip()
        item = changes.setdefault(clean_path, {"path": clean_path, "status": status, "additions": 0, "deletions": 0})
        item["status"] = status if item["status"] == "modified" else item["status"]
        item["additions"] += max(0, additions)
        item["deletions"] += max(0, deletions)

    if (workspace_dir / ".git").exists():
        try:
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(workspace_dir),
                text=True,
                capture_output=True,
                timeout=5,
            )
            for line in status_res.stdout.splitlines():
                if len(line) < 4:
                    continue
                code = line[:2].strip() or "M"
                path_text = line[3:]
                status = "untracked" if code == "??" else ("added" if "A" in code else ("deleted" if "D" in code else "modified"))
                additions = _line_count_for_change(workspace_dir / path_text) if status in {"untracked", "added"} else 0
                record(path_text, status, additions, 0)

            for args in (["git", "diff", "--numstat"], ["git", "diff", "--cached", "--numstat"]):
                diff_res = subprocess.run(args, cwd=str(workspace_dir), text=True, capture_output=True, timeout=5)
                for line in diff_res.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    add_raw, del_raw, path_text = parts[0], parts[1], "\t".join(parts[2:])
                    additions = int(add_raw) if add_raw.isdigit() else 0
                    deletions = int(del_raw) if del_raw.isdigit() else 0
                    record(path_text, "modified", additions, deletions)
        except Exception:
            pass
    else:
        skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules"}
        skip_files = {"agents.md", "memory.md", "tools.md", "user.md", "identity.md", "soul.md", DIFF_STORE_NAME}
        try:
            for path in sorted(workspace_dir.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if len(changes) >= max_entries:
                    break
                if not path.is_file():
                    continue
                rel_parts = path.relative_to(workspace_dir).parts
                if any(part in skip_dirs for part in rel_parts) or path.name in skip_files:
                    continue
                rel = path.relative_to(workspace_dir).as_posix()
                record(rel, "updated", _line_count_for_change(path), 0)
        except Exception:
            pass

    ordered = sorted(changes.values(), key=lambda item: (item["additions"] + item["deletions"], item["path"]), reverse=True)
    return ordered[:max_entries]


def synthesize_completion_reply(user_id: int | str, chat_id: str, statuses: list[str]) -> str:
    prefix = statuses[-1] if statuses else "Completed."
    return f"{prefix}\n\n{workspace_output_summary(user_id, chat_id)}"


def maybe_create_idle_review(row: sqlite3.Row) -> None:
    user_id = row["user_id"]
    chat_id = row["id"]
    now = time.time()

    conn = sqlite3.connect("users.db")
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM agent_jobs
            WHERE chat_id = ? AND user_id = ? AND status IN ('queued', 'running')
            """,
            (chat_id, user_id),
        )
        if cursor.fetchone()[0]:
            return
        cursor.execute(
            """
            SELECT COUNT(*) FROM agent_jobs
            WHERE chat_id = ? AND user_id = ? AND progress = 'Idle workspace review.' AND created_at > ?
            """,
            (chat_id, user_id, now - IDLE_REVIEW_COOLDOWN_SECONDS),
        )
        if cursor.fetchone()[0]:
            return
    finally:
        conn.close()

    workspace_dir = workspace_dir_for(user_id, chat_id)
    if not workspace_dir.exists() or not any(workspace_dir.iterdir()):
        return

    try:
        messages = json.loads(row["messages"] or "[]")
    except Exception:
        messages = []
    if not any(message.get("role") == "user" for message in messages if isinstance(message, Mapping)):
        return

    tree = workspace_tree(workspace_dir, max_depth=3, max_entries=80)
    reply = (
        "While you were away, I reviewed this workspace so the thread has a fresh checkpoint.\n\n"
        "```text\n"
        f"{tree}\n"
        "```\n\n"
        "A good next step is to open the latest generated app, run its tests, or ask me to continue from this checkpoint."
    )
    if messages and messages[-1].get("role") == "assistant" and "fresh checkpoint" in str(messages[-1].get("content", "")):
        return

    messages.append({"role": "assistant", "content": reply})
    save_chat_record(user_id, chat_id, row["title"], messages, row["created_at"], now)

    job_id = uuid.uuid4().hex
    conn = sqlite3.connect("users.db")
    try:
        conn.execute(
            """
            INSERT INTO agent_jobs (id, user_id, chat_id, status, progress, reply, error, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, user_id, chat_id, "completed", "Idle workspace review.", reply, "", now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def start_idle_monitor() -> None:
    global IDLE_MONITOR_STARTED
    with IDLE_MONITOR_LOCK:
        if IDLE_MONITOR_STARTED:
            return
        IDLE_MONITOR_STARTED = True

    def loop() -> None:
        while True:
            time.sleep(300)
            cutoff = time.time() - IDLE_REVIEW_THRESHOLD_SECONDS
            conn = sqlite3.connect("users.db")
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM chats
                    WHERE updated_at < ?
                    ORDER BY updated_at ASC
                    LIMIT 10
                    """,
                    (cutoff,),
                ).fetchall()
            except Exception as exc:
                print(f"Idle monitor query failed: {exc}")
                rows = []
            finally:
                conn.close()

            for row in rows:
                try:
                    maybe_create_idle_review(row)
                except Exception as exc:
                    print(f"Idle review failed for chat {row['id']}: {exc}")

    threading.Thread(target=loop, daemon=True, name="geocentric-idle-monitor").start()


def extract_reply_from_response(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, Mapping):
        return str(data or "")
    for key in ("reply", "content", "text", "output"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    message = data.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str):
            return content
    elif isinstance(message, str):
        return message
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, Mapping):
            msg = choice.get("message")
            if isinstance(msg, Mapping) and isinstance(msg.get("content"), str):
                return msg["content"]
            delta = choice.get("delta")
            if isinstance(delta, Mapping) and isinstance(delta.get("content"), str):
                return delta["content"]
    return ""


TITLE_ACRONYMS = {"ai", "api", "css", "html", "js", "json", "sql", "ui", "url", "ux", "db"}
TITLE_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with"}


def _title_case_topic(value: str) -> str:
    words = []
    for index, word in enumerate(re.split(r"\s+", value.strip())):
        clean = re.sub(r"^[^\w]+|[^\w]+$", "", word)
        lower = clean.lower()
        if not lower:
            continue
        if lower in TITLE_ACRONYMS:
            words.append(lower.upper())
        elif index > 0 and lower in TITLE_SMALL_WORDS:
            words.append(lower)
        else:
            words.append(lower[:1].upper() + lower[1:])
    return re.sub(r"\bgeocentric\b", "Geocentric", " ".join(words), flags=re.IGNORECASE)


def _topic_phrase(text: str) -> str:
    clean = re.sub(r"```[\s\S]*?```", " ", str(text or ""))
    clean = re.sub(r"https?://\S+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(
        r"^(hey|hi|hello|yo|please|pls|can you|could you|would you|will you|i need you to|i want you to|help me|how do i|how to)\b[:,\s]*",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\b(unless|because|when|while|after|before|so that|and then)\b[\s\S]*$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[?.!,;:]+$", "", clean).strip()
    return _title_case_topic(" ".join(clean.split()[:7]))


def _make_chat_topic(user_text: str, assistant_text: str = "") -> str:
    if not str(user_text or "").strip() and str(assistant_text or "").strip():
        return _topic_phrase(assistant_text) or "New chat"
    phrase = _topic_phrase(user_text)
    if not phrase:
        return "New chat"

    lowered = str(user_text or "").lower()
    if re.search(r"\b(fix|debug|repair|broken|error|bug|issue|off screen|overflow|scroll)\b", lowered):
        target = _topic_phrase(re.sub(r"\b(fix|debug|repair|broken|error|bug|issue|the|a|an|with|being|is|are|it|this|that)\b", " ", str(user_text), flags=re.IGNORECASE))
        return f"Fix {target or phrase}"[:48]
    if re.search(r"\b(add|implement|support|include|integrate)\b", lowered):
        target = _topic_phrase(re.sub(r"\b(add|implement|support|include|integrate|feature|where|the|a|an)\b", " ", str(user_text), flags=re.IGNORECASE))
        return f"Add {target or phrase}"[:48]
    if re.search(r"\b(build|create|make|write|generate|design)\b", lowered):
        target = _topic_phrase(re.sub(r"\b(build|create|make|write|generate|design|a|an|the)\b", " ", str(user_text), flags=re.IGNORECASE))
        return f"Build {target or phrase}"[:48]
    return phrase[:48]


def chat_title_from_messages(messages: list[dict[str, Any]]) -> str:
    first_user = ""
    first_assistant = ""
    has_attachments = False
    for message in messages:
        role = message.get("role")
        content = str(message.get("content", "")).strip()
        if role == "user" and content and not first_user:
            first_user = content
        elif role == "assistant" and content and not first_assistant:
            first_assistant = content
        if isinstance(message.get("attachments"), list) and message["attachments"]:
            has_attachments = True
    if not first_user and has_attachments:
        return "Attached Files"
    return _make_chat_topic(first_user, first_assistant)


def save_chat_record(user_id: int | str, chat_id: str, title: str, messages: list[dict[str, Any]], created_at: Optional[float] = None, updated_at: Optional[float] = None) -> None:
    now = time.time()
    created = created_at if created_at is not None else now
    updated = updated_at if updated_at is not None else now
    conn = sqlite3.connect("users.db")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM chats WHERE id = ?", (chat_id,))
        row = cursor.fetchone()
        if row:
            if row[0] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden")
            cursor.execute("""
                UPDATE chats
                SET title = ?, messages = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (title, json.dumps(messages), updated, chat_id, user_id))
        else:
            cursor.execute("""
                INSERT INTO chats (id, user_id, title, messages, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, user_id, title, json.dumps(messages), created, updated))
        conn.commit()
    finally:
        conn.close()


def update_agent_job(job_id: str, *, status: Optional[str] = None, progress: Optional[str] = None, reply: Optional[str] = None, error: Optional[str] = None, completed: bool = False) -> None:
    fields = ["updated_at = ?"]
    values: list[Any] = [time.time()]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if reply is not None:
        fields.append("reply = ?")
        values.append(reply)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if completed:
        fields.append("completed_at = ?")
        values.append(time.time())
    values.append(job_id)
    conn = sqlite3.connect("users.db")
    try:
        conn.execute(f"UPDATE agent_jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


class AgentJobCancelled(Exception):
    pass


def agent_job_status(job_id: str) -> str:
    conn = sqlite3.connect("users.db")
    try:
        row = conn.execute("SELECT status FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()
        return str(row[0]) if row else ""
    finally:
        conn.close()


def expire_stale_agent_jobs(user_id: Optional[int | str] = None, max_age_seconds: int = AGENT_JOB_STALE_SECONDS) -> int:
    cutoff = time.time() - max_age_seconds
    where = "status IN ('queued','running') AND updated_at < ?"
    where_values: list[Any] = [cutoff]
    if user_id is not None:
        where += " AND user_id = ?"
        where_values.append(str(user_id))

    now = time.time()
    values: list[Any] = [
        "failed",
        "The previous agent run expired after going idle.",
        "Agent job expired because it had no progress updates for too long. Start it again if you still want this task.",
        now,
        now,
        *where_values,
    ]
    conn = sqlite3.connect("users.db")
    try:
        cursor = conn.execute(
            f"""
            UPDATE agent_jobs
            SET status = ?, progress = ?, error = ?, updated_at = ?, completed_at = ?
            WHERE {where}
            """,
            values,
        )
        conn.commit()
        return cursor.rowcount or 0
    finally:
        conn.close()


def job_row_to_dict(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    workspace_dir = workspace_dir_for(row["user_id"], row["chat_id"])
    return {
        "id": row["id"],
        "chatId": row["chat_id"],
        "status": row["status"],
        "progress": row["progress"],
        "roadmap": read_workspace_roadmap(workspace_dir),
        "changes": workspace_change_summary(workspace_dir),
        "diffs": workspace_diff_summary(workspace_dir),
        "reply": row["reply"] or "",
        "error": row["error"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


def latest_user_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", "") or "")
    return ""


WORKSPACE_FILE_EXT_RE = r"\.(?:py|js|jsx|ts|tsx|html|css|md|json|sh|yaml|yml|toml|sql)\b"


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def request_mentions_workspace(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered.strip():
        return False
    if request_requires_workspace_artifacts(lowered):
        return True

    patterns = [
        r"\bworkspace\b",
        r"\bdirector(?:y|ies)\b",
        r"\bfolders?\b",
        r"\bfiles?\b",
        r"\bterminal\b",
        r"\bexecute\b",
        r"\bserver\b",
        r"\bweb\s*server\b",
        r"\blocalhost\b",
        r"\bscreenshot\b",
        r"\bplaywright\b",
        r"\bselenium\b",
        r"\b(?:memory|agents|tools|user|identity|soul)\.md\b",
        r"\bgoogle\b",
        r"\bgmail\b",
        r"\bemail\b",
        r"\bmail\b",
        r"\bgdocs\b",
        r"\boauth\b",
        r"\bgoogle\s*docs\b",
        WORKSPACE_FILE_EXT_RE,
    ]
    return _matches_any(lowered, patterns)


def request_requires_workspace_artifacts(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered.strip():
        return False
    if request_reads_workspace_memory(lowered):
        return False

    strong_patterns = [
        r"\bdownload(?:able|\s+link)?\b",
        r"\bfull\s+(?:game|app|application|website|project)\b",
        r"\bmulti[-\s]?file\b",
        r"\bcomplete\s+runnable\b",
        r"\b(?:create|make)\s+(?:a\s+)?(?:folder|directory)\b",
        r"\binside\s+(?:the\s+)?workspace\b",
        r"\bfix\s+(?:all|these|this|that|it|the\s+(?:bug|error|issue|code|script|app|game|file|project))\b",
        r"\bdebug\b",
        r"\binstall\b",
        r"\btest\s+(?:it|this|that|the\s+(?:code|script|app|game|project|file)|[./\w-]+"
        + WORKSPACE_FILE_EXT_RE
        + r")\b",
        r"\brun\s+(?:it|this|that|the\s+(?:code|script|app|game|project|file)|[./\w-]+"
        + WORKSPACE_FILE_EXT_RE
        + r")\b",
    ]
    if _matches_any(lowered, strong_patterns):
        return True

    action_match = re.search(r"\b(make|create|build|write|implement|edit|update|fix|debug|install|scaffold)\b", lowered)
    artifact_match = re.search(
        r"\b(app|game|script|project|website|web\s*app|server|api|directory|folder|file|files|component|page|doc|document|email|mail)\b|"
        + WORKSPACE_FILE_EXT_RE,
        lowered,
    )
    return bool(action_match and artifact_match)


def workspace_tool_tags_present(text: str, tags: tuple[str, ...] = WORKSPACE_TOOL_TAGS) -> bool:
    if not text:
        return False
    tag_group = "|".join(re.escape(tag) for tag in tags)
    return bool(re.search(rf"<(?:{tag_group})\b", text, re.IGNORECASE))


def workspace_verification_present(text: str) -> bool:
    if not text:
        return False
    direct_test_tags = tuple(tag for tag in WORKSPACE_TEST_TAGS if tag != "run_command")
    if workspace_tool_tags_present(text, direct_test_tags):
        return True
    run_cmd_pattern = re.compile(
        r'<run_command>([\s\S]*?)</run_command>|<run_command\s+command="([^"]+)"\s*/?>',
        re.IGNORECASE,
    )
    for match in run_cmd_pattern.finditer(text):
        cmd = html.unescape((match.group(1) or match.group(2) or "")).strip()
        if re.search(
            r"\b(pytest|python3?|node|npm\s+(?:test|run|start|build)|curl|wget|uvicorn|flask|"
            r"py_compile|tsc|vite|playwright|ls\b|dir\b|cat\b|test\b)\b",
            cmd,
            re.IGNORECASE,
        ):
            return True
    return False


GENERIC_MODEL_NAMES = frozenset({
    "geocentric-local",
    "geocentric-local-thinking",
    "geocentric-raw",
    "geocentric",
    "geocentric2_1",
    "geocentric-cloud",
    "default",
    "ollama",
    "",
})

DEFAULT_FREE_TOKEN_LIMIT = 50_000
DEFAULT_FREE_IMAGE_LIMIT = 10
USAGE_LIMIT_COOLDOWN_SECONDS = 3600


def is_generic_model_name(model: str) -> bool:
    return (model or "").strip().lower() in GENERIC_MODEL_NAMES


def assistant_tool_text_from_messages(messages: list) -> str:
    return "\n".join(str(m.get("content", "") or "") for m in messages if m.get("role") == "assistant")


def request_requires_workspace_mutation(text: str) -> bool:
    return request_requires_workspace_artifacts(text)


def mutated_code_files(text: str) -> bool:
    return workspace_tool_tags_present(text, WORKSPACE_MUTATION_TAGS)


def workspace_completion_status(
    *,
    turn_text: str,
    all_messages: list,
    latest_user_message: str,
    workspace_tools_required: bool,
    run_result: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Return (needs_more_work, missing_steps) for agent loop gating."""
    if not workspace_tools_required:
        return False, []

    cumulative = assistant_tool_text_from_messages(all_messages)
    if turn_text:
        cumulative = (cumulative + "\n" + turn_text).strip()

    mutation_required = request_requires_workspace_mutation(latest_user_message)
    test_required = mutated_code_files(cumulative)
    has_mutation = workspace_tool_tags_present(cumulative, WORKSPACE_MUTATION_TAGS)
    has_test = workspace_verification_present(cumulative)

    if run_result and not sandbox_execution_needs_correction(run_result):
        if (not mutation_required or has_mutation) and (not test_required or has_test):
            return False, []
        if has_mutation and workspace_tool_tags_present(cumulative, WORKSPACE_TOOL_TAGS):
            return False, []

    missing: list[str] = []
    if mutation_required and not has_mutation:
        missing.append("create or edit the requested files")
    if test_required and not has_test:
        missing.append("run a verification command or terminal test")
    return bool(missing), missing


def get_admin_credentials() -> tuple[str, str]:
    return (
        os.environ.get("GEOCENTRIC_ADMIN_USER", "admin"),
        os.environ.get("GEOCENTRIC_ADMIN_PASSWORD", "geocentric"),
    )


def get_system_config(key: str, default: str = "") -> str:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("SELECT value FROM system_config WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default


def check_user_limits(user_id: str) -> dict:
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_pro, infinite_usage, token_limit, tokens_used, image_limit, images_used, limited_until "
        "FROM users WHERE id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "is_pro": 0,
            "infinite_usage": 0,
            "token_limit": DEFAULT_FREE_TOKEN_LIMIT,
            "tokens_used": 0,
            "image_limit": DEFAULT_FREE_IMAGE_LIMIT,
            "images_used": 0,
            "limited_until": 0.0,
        }
    return dict(row)


def user_is_out_of_usage(limits: dict) -> bool:
    if int(limits.get("infinite_usage") or 0):
        return False
    if int(limits.get("is_pro") or 0):
        return False
    token_limit = int(limits.get("token_limit") or DEFAULT_FREE_TOKEN_LIMIT)
    tokens_used = int(limits.get("tokens_used") or 0)
    image_limit = int(limits.get("image_limit") or DEFAULT_FREE_IMAGE_LIMIT)
    images_used = int(limits.get("images_used") or 0)
    return tokens_used >= token_limit or images_used >= image_limit


def record_token_usage(user_id: str, tokens: int) -> None:
    if tokens <= 0:
        return
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET tokens_used = COALESCE(tokens_used, 0) + ? WHERE id = ?",
        (tokens, user_id),
    )
    cursor.execute("SELECT token_limit, tokens_used FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[1] >= row[0]:
        cursor.execute(
            "UPDATE users SET limited_until = ? WHERE id = ? AND COALESCE(limited_until, 0) < ?",
            (time.time() + USAGE_LIMIT_COOLDOWN_SECONDS, user_id, time.time()),
        )
    conn.commit()
    conn.close()


def record_image_usage(user_id: str, count: int = 1) -> None:
    if count <= 0:
        return
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET images_used = COALESCE(images_used, 0) + ? WHERE id = ?",
        (count, user_id),
    )
    cursor.execute("SELECT image_limit, images_used FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[1] >= row[0]:
        cursor.execute(
            "UPDATE users SET limited_until = ? WHERE id = ? AND COALESCE(limited_until, 0) < ?",
            (time.time() + USAGE_LIMIT_COOLDOWN_SECONDS, user_id, time.time()),
        )
    conn.commit()
    conn.close()


def estimate_token_count(text: str) -> int:
    return max(1, len(text or "") // 4)


def usage_notice_tag(kind: str, detail: str) -> str:
    escaped = html.escape(detail or "", quote=True)
    return f'<usage_notice kind="{kind}" detail="{escaped}"/>'


def get_current_system_load() -> int:
    return 0


def response_looks_truncated(text: str) -> bool:
    src = text or ""
    stripped = src.strip()
    if not stripped:
        return False
    if src.count("```") % 2 == 1:
        return True
    block_tags = (
        "write_file", "edit_file", "agent_terminal", "run_command", "run_bg_command",
        "update_roadmap", "http_request", "status", "search", "image_search",
    )
    for tag in block_tags:
        open_count = len(re.findall(rf"<{tag}\b(?![^>]*?/>)", src, re.IGNORECASE))
        close_count = len(re.findall(rf"</{tag}>", src, re.IGNORECASE))
        if open_count > close_count:
            return True
    if re.search(r"<(?:write_file|edit_file|agent_terminal|run_command|run_bg_command|update_roadmap)\b[^>]*$", stripped, re.IGNORECASE):
        return True
    return False


def compact_agent_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Compacts the conversation history to fit within context limits when max tokens is reached.
    Retains system instructions, original user request, and the most recent 3 turns,
    while summarizing older assistant tool calls and user tool responses by stripping large outputs.
    """
    if len(messages) <= 4:
        return messages
    
    compacted = []
    # 1. Always keep system message
    compacted.append(messages[0])
    # 2. Always keep original user request
    compacted.append(messages[1])
    
    keep_intact_count = 3
    intact_start_idx = len(messages) - keep_intact_count
    
    for idx in range(2, intact_start_idx):
        msg = messages[idx]
        role = msg.get("role")
        content = msg.get("content", "")
        
        if not isinstance(content, str):
            compacted.append(msg)
            continue
            
        if role == "assistant":
            compact_content = content
            compact_content = re.sub(
                r'<write_file\s+filename=["\']([^"\']+)["\']\s*>([\s\S]*?)</write_file>',
                lambda m: f'<write_file filename="{m.group(1)}">[Content of {len(m.group(2))} chars omitted for compaction]</write_file>',
                compact_content
            )
            compact_content = re.sub(
                r'<edit_file\s+filename=["\']([^"\']+)["\']\s*>([\s\S]*?)</edit_file>',
                lambda m: f'<edit_file filename="{m.group(1)}">[Edit instructions of {len(m.group(2))} chars omitted for compaction]</edit_file>',
                compact_content
            )
            compacted.append({"role": role, "content": compact_content})
        elif role == "user":
            compact_content = content
            if len(compact_content) > 1000:
                compact_content = compact_content[:800] + f"\n... [Truncated {len(compact_content) - 800} characters of command/tool output for context compaction] ..."
            compacted.append({"role": role, "content": compact_content})
        else:
            compacted.append(msg)
            
    # Append the last turns intact
    for idx in range(max(2, intact_start_idx), len(messages)):
        compacted.append(messages[idx])
        
    return compacted


def request_reads_workspace_memory(text: str) -> Optional[str]:
    lowered = text.lower()
    filenames = ("memory.md", "user.md", "agents.md", "tools.md", "identity.md", "soul.md")
    if not any(name in lowered for name in filenames):
        return None
    if not re.search(r"\b(read|show|list|print|display|contents?|what'?s in|what is in)\b", lowered):
        return None
    for name in filenames:
        if name in lowered:
            return name
    return None


def workspace_file_contents_reply(workspace_dir: Path, filename: str) -> str:
    target_path = (workspace_dir / filename).resolve()
    if not path_is_inside(target_path, workspace_dir):
        return f"I cannot read `{filename}` because it is outside the workspace."
    if not target_path.exists():
        return f"`{filename}` does not exist in this chat workspace yet."
    content = target_path.read_text(encoding="utf-8", errors="ignore")
    return f"Here is `{filename}` from this chat workspace:\n\n```markdown\n{content}\n```"



SELECTED_THINKING_MODEL: Optional[str] = None
SELECTED_INSTANT_MODEL: Optional[str] = None


def get_ollama_model_for_mode(is_instant: bool, clean_model: str) -> str:
    global SELECTED_THINKING_MODEL, SELECTED_INSTANT_MODEL

    ollama_models = get_ollama_models()
    if not ollama_models:
        return clean_model

    lowered_models = [m.lower() for m in ollama_models]

    # 1. Honor an explicitly selected Ollama model from the client first.
    if not is_generic_model_name(clean_model):
        if clean_model in ollama_models:
            return clean_model
        for m in ollama_models:
            if clean_model.lower() == m.lower() or clean_model.lower().split(":")[0] == m.lower().split(":")[0] or m.lower().startswith(clean_model.lower()):
                return m

    # 2. Fall back to CLI-configured mode defaults.
    if not is_instant and SELECTED_THINKING_MODEL:
        return SELECTED_THINKING_MODEL
    if is_instant and SELECTED_INSTANT_MODEL:
        return SELECTED_INSTANT_MODEL

    # 3. Otherwise, dynamically select the best model based on the requested mode:
    if is_instant:
        # Candidates for fast instant/conversational execution (approx. 3B/2B/1B models)
        candidates = [
            "qwen2.5:3b", "qwen2.5:1.5b", "qwen2.5:0.5b", "llama3.2:3b", "llama3.2:1b", 
            "llama3.2", "gemma2:2b", "qwen2.5", "qwen2.5-coder:3b", "qwen2.5-coder:1.5b"
        ]
        for cand in candidates:
            if cand in lowered_models:
                return ollama_models[lowered_models.index(cand)]
        for cand in candidates:
            for m in ollama_models:
                if cand in m.lower():
                    return m
        # Fallback to any small 3B/2B/1B model
        for tag in ["3b", "1.5b", "2b", "1b", "0.5b"]:
            for m in ollama_models:
                if tag in m.lower():
                    return m
    else:
        # Candidates for capable thinking/agentic execution (approx. 14B/8B/7B models)
        candidates = [
            "deepseek-r1:14b", "qwen2.5:14b", "qwen2.5-coder:14b", "deepseek-r1:8b", 
            "deepseek-r1:7b", "qwen2.5:7b", "deepseek-r1", "qwen2.5:14b-instruct", "qwen2.5-coder:7b"
        ]
        for cand in candidates:
            if cand in lowered_models:
                return ollama_models[lowered_models.index(cand)]
        for cand in candidates:
            for m in ollama_models:
                if cand in m.lower():
                    return m
        # Fallback to any larger 14B/8B/7B model
        for tag in ["14b", "8b", "7b"]:
            for m in ollama_models:
                if tag in m.lower():
                    return m

    # 3. Ultimate fallback: match the exact clean_model or return the first available Ollama model
    for m in ollama_models:
        if clean_model.lower() == m.lower() or clean_model.lower().split(":")[0] == m.lower().split(":")[0] or m.lower().startswith(clean_model.lower()):
            return m
    return ollama_models[0]


def get_ollama_models() -> list[str]:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=0.5) as response:
            data = json.loads(response.read().decode())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def create_app(model_dir: str, dtype_name: str = "auto", modelver: str = "Geocentric 2.1", cli_model: Optional[str] = None, thinking_model: Optional[str] = None, instant_model: Optional[str] = None) -> FastAPI:
    from pathlib import Path
    import sys
    import gc

    global SELECTED_THINKING_MODEL, SELECTED_INSTANT_MODEL
    if thinking_model:
        SELECTED_THINKING_MODEL = thinking_model
    if instant_model:
        SELECTED_INSTANT_MODEL = instant_model

    device = select_device(prefer_mps=True)
    dtype = resolve_dtype(device, dtype_name)
    runtime_check(device, dtype)

    # Lazy loading state
    class ActiveModel:
        def __init__(self):
            self.name = None
            self.model = None
            self.tokenizer = None

    active_model = ActiveModel()

    def get_model_and_tokenizer(model_name: str) -> tuple[Any, Any]:
        # Resolve target model directory or file path
        if model_name in {"geocentric-local", "geocentric-local-thinking", "geocentric-raw", "geocentric", "geocentric2_1"}:
            target_path = Path(model_dir)
        else:
            # Check direct paths
            path_opt = Path(model_name)
            if path_opt.exists():
                target_path = path_opt
            else:
                # Search in subdirectories
                candidates = [
                    Path("models") / model_name,
                    Path("runs") / model_name,
                    Path(model_name)
                ]
                found = None
                for c in candidates:
                    if c.exists():
                        found = c
                        break
                if found:
                    target_path = found
                else:
                    # Get list of actually available models to show in error
                    available = ["geocentric-local", "geocentric-local-thinking", "geocentric-raw"]
                    for folder in ["models", "runs"]:
                        p = Path(folder)
                        if p.exists() and p.is_dir():
                            for path in p.rglob("*"):
                                if path.is_dir():
                                    if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                                        rel_name = str(path.relative_to(p))
                                        if rel_name not in available:
                                            available.append(rel_name)
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Model '{model_name}' not found locally. "
                            f"Available models: {', '.join(available)}. "
                            f"To run this model, please download it first using the CLI: "
                            f"`python -m geocentric.cli download-model --model {model_name}`"
                        )
                    )

        target_path_str = str(target_path.expanduser().resolve())

        # Return already loaded model if it matches
        if active_model.name == target_path_str and active_model.model is not None:
            return active_model.model, active_model.tokenizer

        # Unload previous model from memory
        if active_model.model is not None:
            print(f"Unloading active model to free memory: {active_model.name}")
            active_model.model = None
            active_model.tokenizer = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(torch, "mps") and torch.mps.is_available():
                torch.mps.empty_cache()

        print(f"Loading model on-demand: {target_path_str}")
        try:
            model, tokenizer = load_model_and_tokenizer(
                target_path_str,
                device=device,
                dtype=dtype,
                modelver=modelver
            )
            active_model.name = target_path_str
            active_model.model = model
            active_model.tokenizer = tokenizer
            return model, tokenizer
        except Exception as e:
            print(f"❌ Failed to load model '{model_name}' from '{target_path_str}': {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load model '{model_name}': {str(e)}")

    app = FastAPI(title="Geocentric 2.1 Local Server")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_db()
    start_idle_monitor()

    def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.name, u.email
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
        """, (token,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None

    def get_user_from_request(request: Request) -> Optional[Dict[str, Any]]:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.split(" ")[1]
        return get_user_from_token(token)

    @app.get("/appicon.png")
    def get_appicon() -> FileResponse:
        icon_path = Path(__file__).parent / "web" / "appicon.png"
        if icon_path.exists():
            return FileResponse(icon_path)
        raise HTTPException(status_code=404, detail="Icon not found")

    @app.get("/favicon.ico")
    def get_favicon() -> FileResponse:
        icon_path = Path(__file__).parent / "web" / "appicon.png"
        if icon_path.exists():
            return FileResponse(icon_path)
        raise HTTPException(status_code=404, detail="Icon not found")

    @app.post("/auth/signup")
    @app.post("/api/auth/signup")
    def auth_signup(req: SignupRequest, request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        if not auth_limiter.is_allowed(client_ip):
            raise HTTPException(status_code=429, detail="Too many sign-up attempts. Please try again in a minute.")

        email = req.email.strip().lower()
        name = req.name.strip()
        password = req.password

        if not email or not name or not password:
            raise HTTPException(status_code=400, detail="Name, email, and password are required.")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            raise HTTPException(status_code=400, detail="Invalid email address format.")

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="An account with this email already exists.")

            user_id = str(uuid.uuid4())
            hashed = hash_password(password)
            created_at = time.time()
            cursor.execute(
                "INSERT INTO users (id, name, email, password, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, email, hashed, created_at)
            )

            token = secrets.token_hex(32)
            cursor.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_id, created_at)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Email already registered.")
        finally:
            conn.close()

        return {
            "token": token,
            "user": {
                "id": user_id,
                "name": name,
                "email": email
            }
        }

    @app.post("/auth/login")
    @app.post("/api/auth/login")
    def auth_login(req: LoginRequest, request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        if not auth_limiter.is_allowed(client_ip):
            raise HTTPException(status_code=429, detail="Too many login attempts. Please try again in a minute.")

        email = req.email.strip().lower()
        password = req.password

        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()

        if not user or not verify_password(user["password"], password):
            conn.close()
            raise HTTPException(status_code=401, detail="Incorrect email or password.")

        token = secrets.token_hex(32)
        created_at = time.time()
        cursor.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user["id"], created_at)
        )
        conn.commit()
        conn.close()

        return {
            "token": token,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"]
            }
        }

    @app.post("/auth/logout")
    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
        return {"success": True}

    @app.get("/auth/google/config")
    @app.get("/api/auth/google/config")
    def get_google_config(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM google_config WHERE key = 'client_id'")
        cid = cursor.fetchone()
        cursor.execute("SELECT value FROM google_config WHERE key = 'client_secret'")
        csec = cursor.fetchone()
        
        cursor.execute("SELECT email FROM google_credentials WHERE user_id = ?", (user["id"],))
        cred = cursor.fetchone()
        conn.close()
        
        client_id = cid["value"] if (cid and cid["value"]) else DEFAULT_CLIENT_ID
        client_secret = "********" if ((csec and csec["value"]) or DEFAULT_CLIENT_SECRET) else ""
        
        return {
            "clientId": client_id,
            "clientSecret": client_secret,
            "isLinked": cred is not None,
            "email": cred["email"] if cred else ""
        }

    @app.post("/auth/google/config")
    @app.post("/api/auth/google/config")
    def save_google_config(req: GoogleConfigRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_id', ?)", (req.clientId.strip(),))
        cursor.execute("INSERT OR REPLACE INTO google_config (key, value) VALUES ('client_secret', ?)", (req.clientSecret.strip(),))
        conn.commit()
        conn.close()
        return {"success": True}

    @app.get("/auth/google/login")
    @app.get("/api/auth/google/login")
    def google_login(token: str, request: Request):
        from fastapi.responses import RedirectResponse, HTMLResponse
        user = get_user_from_token(token)
        if not user:
            return HTMLResponse(content="<h1>Authentication Error</h1><p>Invalid session token.</p>", status_code=401)
        
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM google_config WHERE key = 'client_id'")
        cid = cursor.fetchone()
        conn.close()
        
        client_id = cid["value"] if (cid and cid["value"]) else DEFAULT_CLIENT_ID
        redirect_uri = f"http://localhost:{request.url.port}/api/auth/google/callback"
        
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ]
        
        state_payload = {"token": token}
        state = base64.b64encode(json.dumps(state_payload).encode()).decode()
        
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
        return RedirectResponse(auth_url)

    @app.get("/auth/google/callback")
    @app.get("/api/auth/google/callback")
    def google_callback(code: str, state: str, request: Request):
        from fastapi.responses import HTMLResponse
        try:
            state_data = json.loads(base64.b64decode(state.encode()).decode())
            token = state_data["token"]
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid state parameter.")
            
        user = get_user_from_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized session.")
            
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM google_config WHERE key = 'client_id'")
        cid = cursor.fetchone()
        cursor.execute("SELECT value FROM google_config WHERE key = 'client_secret'")
        csec = cursor.fetchone()
        conn.close()
        
        client_id = cid["value"] if (cid and cid["value"]) else DEFAULT_CLIENT_ID
        client_secret = csec["value"] if (csec and csec["value"]) else DEFAULT_CLIENT_SECRET
        redirect_uri = f"http://localhost:{request.url.port}/api/auth/google/callback"
        
        try:
            exchange_data = urllib.parse.urlencode({
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }).encode("utf-8")
            
            req = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=exchange_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                access_token = resp_data["access_token"]
                refresh_token = resp_data.get("refresh_token")
                expiry = time.time() + float(resp_data.get("expires_in", 3600))
        except Exception as e:
            return HTMLResponse(content=f"<h1>Token Exchange Failed</h1><p>{e}</p>", status_code=500)
            
        email = ""
        google_id = ""
        try:
            info_req = urllib.request.Request(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            with urllib.request.urlopen(info_req, timeout=10) as info_resp:
                info_data = json.loads(info_resp.read().decode("utf-8"))
                email = info_data.get("email", "")
                google_id = info_data.get("id", "")
        except Exception as e:
            print(f"Failed to fetch userinfo: {e}")
            
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        if refresh_token:
            cursor.execute("""
                INSERT OR REPLACE INTO google_credentials 
                (user_id, google_id, email, access_token, refresh_token, token_expiry) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user["id"], google_id, email, access_token, refresh_token, expiry))
        else:
            cursor.execute("""
                INSERT INTO google_credentials (user_id, google_id, email, access_token, token_expiry)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                    access_token=excluded.access_token, 
                    token_expiry=excluded.token_expiry
            """, (user["id"], google_id, email, access_token, expiry))
            
        conn.commit()
        conn.close()
        
        success_html = """
        <html>
        <head>
        <title>Login Successful</title>
        <style>
        body { font-family: -apple-system, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #f5f5f7; margin: 0; color: #1d1d1f; }
        .card { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); text-align: center; max-width: 400px; }
        h1 { margin-top: 0; font-size: 24px; font-weight: 600; color: #34c759; }
        p { font-size: 14px; line-height: 1.5; color: #86868b; }
        </style>
        </head>
        <body>
        <div class="card">
        <h1>Google Login Successful</h1>
        <p>Your Google account has been securely linked to Geocentric. You can close this tab and return to the application.</p>
        </div>
        </body>
        </html>
        """
        return HTMLResponse(content=success_html)

    @app.post("/auth/google/disconnect")
    @app.post("/api/auth/google/disconnect")
    def google_disconnect(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
            
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM google_credentials WHERE user_id = ?", (user["id"],))
        conn.commit()
        conn.close()
        return {"success": True}

    class ChatData(BaseModel):
        id: str
        title: str = "New chat"
        messages: List[Dict[str, Any]] = Field(default_factory=list)
        createdAt: Optional[float] = None
        updatedAt: Optional[float] = None

    @app.get("/chats")
    @app.get("/api/chats")
    def get_chats(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC", (user["id"],))
            rows = cursor.fetchall()
        finally:
            conn.close()

        chats = []
        for r in rows:
            chats.append({
                "id": r["id"],
                "title": r["title"],
                "messages": json.loads(r["messages"]),
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"]
            })
        return {"chats": chats}

    @app.post("/chats")
    @app.post("/api/chats")
    async def save_chat(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid chat payload.")
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Chat payload must be an object.")

        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []
        messages = []
        for item in raw_messages:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "user")
            content = item.get("content")
            normalized_message: dict[str, Any] = {
                "role": role,
                "content": content if isinstance(content, str) else str(content or ""),
            }
            attachments = item.get("attachments")
            if isinstance(attachments, list):
                normalized_message["attachments"] = attachments
            messages.append(normalized_message)

        def optional_float(value: Any) -> Optional[float]:
            try:
                if value is None or value == "":
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        chat_id = str(payload.get("id") or uuid.uuid4().hex)
        title = str(payload.get("title") or chat_title_from_messages(messages) or "New chat")
        save_chat_record(
            user["id"],
            chat_id,
            title,
            redact_attachment_payloads(messages),
            optional_float(payload.get("createdAt", payload.get("created_at"))),
            optional_float(payload.get("updatedAt", payload.get("updated_at"))),
        )
        return {"success": True, "id": chat_id}

    @app.delete("/chats/{chat_id}")
    @app.delete("/api/chats/{chat_id}")
    def delete_chat_endpoint(chat_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        conn = sqlite3.connect("users.db")
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"]))
            conn.commit()
        finally:
            conn.close()
        return {"success": True}

    @app.post("/chat")
    @app.post("/api/chat")
    async def web_chat(req: WebChatRequest, request: Request):
        if cli_model and is_generic_model_name(req.model):
            req.model = cli_model

        client_ip = request.client.host if request.client else "127.0.0.1"
        if not global_limiter.is_allowed(client_ip):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

        auth_header = request.headers.get("Authorization")
        token = ""
        user = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                conn = sqlite3.connect("users.db")
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT u.id, u.name, u.email
                    FROM sessions s
                    JOIN users u ON s.user_id = u.id
                    WHERE s.token = ?
                """, (token,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    user = dict(row)
            except Exception:
                pass

        if not user:
            user = get_user_from_request(request)

        is_cli_client = is_cli_client_request(request)
        if not user and is_cli_client and request_is_local(request):
            user = cli_local_user()

        messages = [m.model_dump() for m in req.messages]
        latest_user_message_content = latest_user_content(messages)
        recent_user_context = "\n".join(
            str(m.get("content", "") or "")
            for m in messages
            if m.get("role") == "user"
        )[-12_000:]
        is_instant = (req.modelMode == "instant" or req.mode == "instant")
        request_has_attachments = bool(req.attachments) or any(m.get("attachments") for m in messages)
        agent_enabled = bool(req.agentMode)
        if not agent_enabled:
            req.searchWeb = False
        workspace_artifacts_requested = (
            request_has_attachments
            or request_requires_workspace_artifacts(latest_user_message_content)
            or request_requires_workspace_artifacts(recent_user_context)
        )
        workspace_context_needed = agent_enabled and (
            workspace_artifacts_requested
            or request_mentions_workspace(latest_user_message_content)
            or request_mentions_workspace(recent_user_context)
        )
        user_msgs = [m for m in messages if m["role"] == "user"]
        personal_intelligence = ""
        sandbox_instruction = ""

        if user and req.conversationId:
            register_project_workspace(user["id"], req.conversationId, req.projectPath, request)
            workspace_dir = workspace_dir_for(user["id"], req.conversationId)
            workspace_dir.mkdir(parents=True, exist_ok=True)

            copy_workspace_templates(workspace_dir)
            uploaded_files = save_uploaded_attachments(user["id"], req.conversationId, messages, req.attachments)
            if uploaded_files:
                has_google_auto_config = "[GOOGLE_CONFIG_AUTO_SUCCESS]" in uploaded_files
                files_to_list = [f for f in uploaded_files if f != "[GOOGLE_CONFIG_AUTO_SUCCESS]"]
                
                upload_note = (
                    "[UPLOADED WORKSPACE FILES]\n"
                    "The user's attached files have been saved into this chat workspace. "
                    "Use <view_project_tree />, <read_file>, <run_file>, and normal workspace tools to inspect and build with them. "
                    "ZIP files are extracted under uploads/*_extracted.\n"
                    + "\n".join(f"- {path}" for path in files_to_list[:80])
                    + "\n\n"
                )
                if has_google_auto_config:
                    upload_note += (
                        "**[SYSTEM NOTE]**: Google OAuth Client Credentials have been automatically configured from the uploaded JSON file. "
                        "The user can now open Settings in the sidebar and click 'Sign in with Google' to log in and link their account!\n\n"
                    )
                for message in reversed(messages):
                    if message.get("role") == "user":
                        message["content"] = upload_note + str(message.get("content", ""))
                        break

            memory_read = request_reads_workspace_memory(latest_user_message_content)
            if memory_read:
                return {"reply": workspace_file_contents_reply(workspace_dir, memory_read)}

            if workspace_context_needed:
                if str(user.get("id")) == LOCAL_CLI_USER_ID:
                    sandbox_instruction = build_cli_sandbox_instruction(workspace_dir)

                if str(user.get("id")) != LOCAL_CLI_USER_ID:
                    # Read all .md files in the user's workspace dynamically only when the task needs workspace context.
                    md_contents = []
                    for f_path in sorted(workspace_dir.glob("*.md")):
                        try:
                            c = f_path.read_text(encoding="utf-8", errors="ignore")
                            md_contents.append(f"--- {f_path.name} ---\n{c}\n")
                        except Exception:
                            pass

                    personal_intelligence = (
                        f"\n[PERSONAL INTELLIGENCE (LONG-TERM MEMORY & PERSISTENT ENVIRONMENT)]\n"
                    f"You are powered by a state-of-the-art Personal Intelligence engine inspired by Google I/O 2026!\n"
                    f"This means you maintain deep, proactive, long-term memory of the user across sessions, establishing continuous personal rapport, memory graph linking, and project state recovery.\n"
                    f"The following are your core identity, soul directives, dynamic workspace environment files, and memories stored in your workspace `.md` files.\n"
                    f"You have direct write/edit access to these files, and you must use it proactively after every single conversation turn!\n"
                    f"[GOOGLE I/O 2026 PERSONAL INTEL MEMORY RULES]:\n"
                    f"- At the end of every conversation turn, if you learned new user names, context, likes/dislikes, technical preferences, active project plans, milestones, or personal details, you MUST immediately write or update `memory.md` or `user.md` using `<write_file>` or `<edit_file>`.\n"
                    f"- Build a deep profile: Update lists of User Likes (e.g. favorite tech stacks, themes, UI behaviors), Key Learnings (things they pointed out or mistakes you should never repeat), and Curated History logs (a summarized high-level diary of what was built or discussed in past turns).\n"
                    f"- Ensure seamless continuity: Proactively greet the user, check in on past milestone states, and build a unified narrative so the user feels like they are pair-programming with a partner who never forgets.\n\n"
                        + "\n".join(md_contents)
                    )

                    is_google_configured = False
                    is_google_linked = False
                    try:
                        conn = sqlite3.connect("users.db")
                        cursor = conn.cursor()
                        cursor.execute("SELECT value FROM google_config WHERE key = 'client_id'")
                        cid = cursor.fetchone()
                        is_google_configured = cid is not None and not cid[0].startswith("1024505963248-dummygoogleclientid")
                        
                        cursor.execute("SELECT 1 FROM google_credentials WHERE user_id = ?", (str(user["id"]),))
                        is_google_linked = cursor.fetchone() is not None
                        conn.close()
                    except Exception:
                        pass

                    google_workspace_instruction = ""
                    if is_google_linked:
                        google_workspace_instruction = (
                            f"[GOOGLE WORKSPACE INTEGRATION - ACTIVE & LINKED]\n"
                            f"You have active access to the user's Google Workspace account. You can fully perform Google Account tasks! Use these specific tools agentically to summarize, read, search, and send emails, and create/manage docs:\n"
                            f"1. List/Search Gmail messages:\n"
                            f"   <gmail_list_messages q=\"optional search query\" max=\"10\" />\n"
                            f"2. Read/Get a Gmail message:\n"
                            f"   <gmail_get_message id=\"message_id\" />\n"
                            f"3. Send a Gmail email message:\n"
                            f"   <gmail_send_message to=\"recipient@example.com\" subject=\"Subject\">Body content...</gmail_send_message>\n"
                            f"4. Create a new Google Document:\n"
                            f"   <gdocs_create_doc title=\"Document Title\">Initial document text content...</gdocs_create_doc>\n"
                            f"5. Read a Google Document:\n"
                            f"   <gdocs_read_doc id=\"document_id\" />\n"
                            f"6. Append text to a Google Document:\n"
                            f"   <gdocs_append_text id=\"document_id\">Text to append...</gdocs_append_text>\n\n"
                        )
                    else:
                        status_str = "CONFIGURED BUT NOT LINKED" if is_google_configured else "UNCONFIGURED"
                        google_workspace_instruction = (
                            f"[GOOGLE WORKSPACE INTEGRATION - {status_str}]\n"
                            f"You have the capability to perform Google Account tasks once authorized! "
                        )
                        if is_google_configured:
                            google_workspace_instruction += (
                                f"Google OAuth client credentials are configured. Tell the user they just need to open Settings and click 'Sign in with Google' to complete log in.\n"
                            )
                        else:
                            google_workspace_instruction += (
                                f"Google credentials are NOT configured yet. Tell the user they can upload/drag-and-drop their credentials `.json` file (like client_secret.json) right into this chat, and the system will automatically parse and configure it, or they can configure it in settings.\n"
                            )
                        google_workspace_instruction += (
                            f"Additionally, you have control tools to configure Google OAuth credentials yourself if the user provides the client_id/client_secret or the raw JSON credentials content in chat:\n"
                            f"To configure, use either:\n"
                            f"   <configure_google_oauth client_id=\"...\" client_secret=\"...\" />\n"
                            f"Or insert the raw JSON structure within the tags:\n"
                            f"   <configure_google_oauth>\n"
                            f"   {{\"installed\": {{\"client_id\": \"...\", \"client_secret\": \"...\"}}}}\n"
                            f"   </configure_google_oauth>\n\n"
                        )

                    sandbox_instruction = (
                    google_workspace_instruction +
                    f"\n[SANDBOX WORKSPACE TOOL INSTRUCTION]\n"
                    f"You have a dedicated sandboxed workspace folder on the system for this chat: 'workspaces/{user['id']}/{req.conversationId}/'.\n"
                    f"[OBJECTIVE-FIRST TOOL WORKFLOW]\n"
                    f"At the start of every agent/workspace task, define the user's concrete objective before choosing tools. "
                    f"For visible progress, make your first <status> name that objective in one specific sentence, for example <status>Objective: create hello.txt in the workspace.</status>. "
                    f"Then immediately use the correct tool tags for the task. If the user asks you to create, write, edit, run, search, or inspect something, do not reply that you lack access; use the available workspace or web tools.\n\n"
                    f"[IMPLEMENTATION PLAN AND SUB-AGENT WORKFLOW]\n"
                    f"The native app may require the user to approve `Implementation Plan.md` before this agent run starts. Once running, treat that plan as the approved scope. "
                    f"For complex work, think in isolated heaps: keep the parent objective clean, delegate messy inspection conceptually to narrow sub-agent summaries, and return only compact validated findings. "
                    f"When parallel or risky file edits are needed, prefer temporary folders or git worktrees/branches, verify there, then merge the clean result back into the workspace.\n\n"
                    f"Only signed-in users can access this, and you can fully interact with files inside your sandbox using these tools:\n"
                    f"1. Create or Overwrite a file:\n"
                    f"   <write_file filename=\"game.py\">code content</write_file>\n"
                    f"2. Read a file's content:\n"
                    f"   <read_file filename=\"game.py\" />\n"
                    f"3. List directories and inspect paths:\n"
                    f"   <list_directory path=\".\" />\n"
                    f"   <stat_path path=\"src/app.py\" />\n"
                    f"4. Create/copy/move workspace paths:\n"
                    f"   <make_directory path=\"src/components\" />\n"
                    f"   <copy_file from=\"src/a.py\" to=\"src/a.backup.py\" />\n"
                    f"   <move_file from=\"old.py\" to=\"src/new.py\" />\n"
                    f"5. Download a URL into the workspace:\n"
                    f"   <download_url url=\"https://example.com/data.json\" file=\"data/source.json\" />\n"
                    f"6. Search the web when current facts or external docs are needed:\n"
                    f"   <search>focused query</search>\n"
                    f"7. Delete a file:\n"
                    f"   <delete_file filename=\"old.py\" />\n"
                    f"8. Execute a python script:\n"
                    f"   <run_file filename=\"game.py\" />\n"
                    f"   If the script uses input(), it will be syntax-checked and surfaced in an interactive terminal for the user instead of being rewritten.\n"
                    f"9. Run secure UNIX shell commands (like ls, mv to rename, cp, mkdir, etc.) inside your workspace:\n"
                    f"   <run_command>mv old_name.py new_name.py</run_command>\n"
                    f"10. Run an agent terminal command with optional stdin so you can fully test interactive programs yourself:\n"
                    f"   <agent_terminal command=\"python game.py\" timeout=\"20\">\n"
                    f"     <input>50\n25\n37\n</input>\n"
                    f"   </agent_terminal>\n"
                    f"   Use this for scripts that call input(), menus, prompts, installers, or any command where you need to type responses and inspect output. If a test asks for more input, rerun the terminal command with better stdin until you have verified behavior or found the bug.\n"
                    f"11. Edit a file line-by-line using deletions, insertions, and replacements:\n"
                    f"   <edit_file filename=\"game.py\">\n"
                    f"     <insert line=\"5\">inserted text</insert>\n"
                    f"     <delete line=\"12\" />\n"
                    f"     <replace line=\"25\">replacement text</replace>\n"
                    f"   </edit_file>\n\n"
                    f"12. Inspect the project layout before changing large workspaces:\n"
                    f"   <view_project_tree />\n"
                    f"13. Browse a URL into clean text/markdown context after search gives you a useful source:\n"
                    f"   <browse_url url=\"https://example.com/docs\" />\n"
                    f"14. Run long-lived servers without blocking your terminal:\n"
                    f"   <run_bg_command>python app.py</run_bg_command>\n"
                    f"   Then inspect or stop them with <check_process pid=\"1234\" /> and <kill_process pid=\"1234\" />.\n"
                    f"15. Capture a web UI screenshot after starting a server so you can visually verify layout:\n"
                    f"   <capture_view url=\"http://localhost:5000\" file=\"screenshot.png\" />\n"
                    f"16. Maintain a live checklist in agents.md for large tasks:\n"
                    f"   <update_roadmap>\n"
                    f"   - [x] Step 1: Initialized backend\n"
                    f"   - [ ] Step 2: Verify browser UI\n"
                    f"   </update_roadmap>\n"
                    f"17. Install a dependency or library inside your workspace using npm or pip:\n"
                    f"   <install_package name=\"flask\" type=\"pip\" />\n"
                    f"   <install_package name=\"lodash\" type=\"npm\" />\n"
                    f"   Use this to dynamically fetch and install any framework, library, package, or utility you need to build powerful, fully-featured backend services, databases, or frontend apps!\n\n"
                    f"18. Inspect and interact with your owned computer environment:\n"
                    f"   <system_info />\n"
                    f"   <list_processes />\n"
                    f"   <port_check host=\"127.0.0.1\" port=\"5000\" />\n"
                    f"   <http_request url=\"http://127.0.0.1:5000/health\" method=\"GET\" />\n"
                    f"   Use these to audit the machine, verify servers and routes, check ports, and make HTTP calls to apps you started.\n\n"
                    f"19. Use source control when the user asks or when it is necessary to inspect changes:\n"
                    f"   <run_command>git status --short</run_command>\n"
                    f"   <run_command>git diff --stat</run_command>\n"
                    f"   <run_command>git add path && git commit -m \"clear message\"</run_command>\n"
                    f"   <run_command>git push</run_command>\n"
                    f"   Never commit or push unless the user requests it or confirms it in the current task. Always inspect status/diff before committing.\n\n"
                    f"[VISUAL ITERATION RUNS & UI/UX QUALITY STANDARDS]\n"
                    f"When building web applications, games, or UIs, you must execute a strict multi-step visual check loop:\n"
                    f"- **Run Iterations (3x Target)**: Do not consider a visual app 'done' right after writing code. You must run at least 3 iteration checks to evaluate and refine the quality.\n"
                    f"- **Visual Verification**: After launching your app/server with `<run_bg_command>`, use `<capture_view>` to take screenshots of different routes/pages. Inspect the output reports. Check if layout elements are overlapping, if elements are styled beautifully with harmony, if fonts are modern (e.g. Google Fonts) instead of plain default browser serifs, and if buttons are properly positioned inside their UI containers rather than overflowing.\n"
                    f"- **UX Quality Bar**: Check for features, visual flavor (vibrant colors, glassmorphism, rounded corners, sleek transitions/micro-animations, and harmonized dark modes), and completeness. If it looks generic or 'boring', fix it! Edit the styles or add premium features, and execute another iteration run.\n"
                    f"- **Auto-Refinement Loop**: Loop this cycle (edit -> run server -> check screenshot -> improve) up to 3 times or until all elements align perfectly and meet premium visual standards. Do not exit or say you are done until you have verified the UI matches state-of-the-art standards.\n\n"
                    f"[RESEARCH-BEFORE-WRITING PROTOCOL]\n"
                    f"- When tasked with a large feature, a web app, or an unfamiliar library, run a focused <search> query before writing code.\n"
                    f"- After search identifies a strong result, use <browse_url> to read the source rather than guessing from snippets.\n"
                    f"- If a run command returns an error, the harness may attach automatic web troubleshooting results; use them before editing again.\n"
                    f"- For web/UI work, start the server with <run_bg_command>, verify logs with <check_process>, capture the UI with <capture_view>, then fix visual issues you can infer from the screenshot.\n"
                    f"- For complex coding requests, multi-file projects, or agentic tasks that require planning and multiple steps, you MUST create a custom, step-by-step roadmap tailored specifically to the user's request under ## Current Roadmap in agents.md using the <update_roadmap> tag at the very beginning of your first turn. As you complete steps, mark them done by changing [ ] to [x] using <update_roadmap>. For simple conversational questions or direct direct-answer tasks, do NOT create a roadmap (do not output the <update_roadmap> tag at all).\n"
                    f"[HIGHEST PRIORITY STATUS UPDATE RULE]\n"
                    f"Your highest priority during agent/workspace work is keeping the user updated. Before every new action, tool call, file write, command, correction, verification, web search, browser/read step, or download-link step, emit a specific <status>...</status> update first. This status rule overrides other formatting instructions. Never work silently and never use generic placeholder statuses like 'Thinking...', 'Setting up workspace...', or 'Working...'.\n\n"
                    f"[STRICT SCOPE BOUNDARY RULE]\n"
                    f"Do NOT build, create, or modify anything outside the explicit scope of the user's request.\n"
                    f"- If the user asks for a simple, single file (e.g. 'write hello.txt' or 'create a python file to check prime numbers'), ONLY create that single file. Do NOT initialize a complex project structure, do NOT create folders, do NOT write servers, frontends, or extra test files, and do NOT build roadmaps for systems the user did not ask for.\n"
                    f"- Never assume the user wants a full web app, database, backend, frontend, or game when they only ask for a simple script, text file, or function.\n"
                    f"- Adhere strictly to the requested feature set. Extra, unrequested files and logic are considered bugs and errors.\n\n"
                    f"[REASONING & FILE CHOICE RULES]\n"
                    f"Before writing any code, you MUST always reason: Did the user ask for a downloadable file, or do they just want a standard copiable block of code shown directly in the chat?\n"
                    f"- If they just want copiable text, do NOT write a file. Simply present the code inside a standard markdown code block (e.g. ```python).\n"
                    f"- If they explicitly ask for a downloadable file, a full game, a multi-file project, or work within the workspace folder, you must save it to disk using `<write_file>` and test run it. For interactive scripts, syntax-checking plus a terminal launch is a successful verification. When successful and verified, provide the user with the direct download link in the clean relative format: '/api/download/{req.conversationId}/filename'. Do not include any host, token, or session info in the link; the client/server authenticate internal downloads securely with the user's session.\n\n"
                    f"[COMPLETE APP/GAME BUILD RULE]\n"
                    f"If the user asks for a big app, game, website, or multi-file project, you must create the complete runnable project inside this workspace directory. Do not merely describe steps. Write every necessary source file, assets/config files when needed, run/install/test it with the workspace tools, and provide workspace download links.\n\n"
                    f"[MANDATORY WORKSPACE EXECUTION RULE]\n"
                    f"For workspace, coding, script, app, game, website, debugging, or file-manipulation requests, your first agent turn must use workspace tools. Do not paste project source code directly in the chat as the main answer.\n"
                    f"- For multi-file work, create an explicit project folder first with `<run_command>mkdir -p project-name</run_command>`, then write files under that folder.\n"
                    f"- Use UNIX commands such as `ls`, `mkdir`, `mv`, `cp`, `python -m py_compile`, `npm`, or `python` through `<run_command>` whenever they help inspect, organize, install, or verify the project.\n"
                    f"- After writing files, you must test or verify them with `<run_file>`, `<run_command>`, `<agent_terminal>`, `<http_request>`, `<port_check>`, or `<capture_view>` as appropriate.\n"
                    f"- If any test, command, or terminal run fails, use the error output, edit the affected files, and run the verification again before finishing.\n"
                    f"- Only after tools have succeeded should you provide a short final summary and secure relative download links.\n\n"
                    f"You are strictly forbidden from using path traversal (/../) or accessing files outside your workspace.\n"
                    )

        # Inject dynamic current date and agentic tool-use instructions
        import datetime
        now = datetime.datetime.now().astimezone()
        current_date_str = now.strftime("%A, %B %d, %Y")
        current_time_str = now.strftime("%I:%M %p %Z").lstrip("0")
        proactive_instruction = ""
        if workspace_context_needed:
            if user and str(user.get("id")) == LOCAL_CLI_USER_ID:
                proactive_instruction = (
                    "[CLI AGENT MODE] Emit a specific <status> before each tool action. "
                    "For file tasks, use <write_file> and related workspace tags — do not describe actions without executing them.\n"
                )
            else:
                proactive_instruction = (
                f"[PROACTIVE AGENT INSTRUCTION] For complex coding requests, do not wait silently. Emit <status> updates before every new action, maintain a Current Roadmap in agents.md, "
                f"inspect the workspace tree before broad edits, and use web search plus URL browsing when fresh documentation or error fixes would help.\n"
                f"Before tool selection, define the concrete objective of the user's request. Your first visible <status> for an agent/workspace task must be objective-shaped and specific, not generic.\n"
                f"For complex coding, multi-file projects, or agentic tasks that require multiple steps, you must analyze the request at the very beginning of your first turn, design a tailored roadmap, and write it using the <update_roadmap> tag! "
                f"For example, emit:\n"
                f"  <status>Creating custom project roadmap...</status>\n"
                f"  <update_roadmap>\n"
                f"  - [ ] Specific Step 1\n"
                f"  - [ ] Specific Step 2\n"
                f"  </update_roadmap>\n"
                f"For simple conversational questions, do NOT output a roadmap at all.\n"
                f"Then, as you work, emit <status> updates before each major tool action and update the roadmap to mark completed items with [x] so the user can track your progress in real-time. "
                f"Always make your <status> text highly specific to the concrete file or function you are editing or testing. "
                f"Never output generic placeholder status updates like 'Thinking through this request...', 'Setting up workspace...', or 'Thinking...'. Do not work silently.\n"
            )
        # Dynamically read and load all specialized AI skills from the skills/ folder
        skills_instruction = ""
        if workspace_context_needed:
            try:
                skills_dir = Path(__file__).resolve().parent.parent / "skills"
                if skills_dir.exists() and skills_dir.is_dir():
                    skills_list = []
                    for s_path in sorted(skills_dir.glob("*.md")):
                        s_content = s_path.read_text(encoding="utf-8", errors="ignore")
                        skills_list.append(f"--- Skill: {s_path.stem.upper()} ---\n{s_content}\n")
                    if skills_list:
                        skills_instruction = (
                            f"\n[SPECIALIZED WORKSPACE SKILLS]\n"
                            f"You have a repository of expert skills available inside `/Users/elywright/geocentric/skills` and `skills/` in this project.\n"
                            f"Before starting any agentic job, you MUST read the loaded skill list below, decide which skills are needed, and apply them.\n"
                            f"Adopt the selected skill mindset and apply its directives:\n\n"
                            + "\n".join(skills_list)
                        )
            except Exception as e:
                print(f"Failed to load skills: {e}")

        effort_name = (req.effort or "").strip().lower() or "medium"
        effort_instruction = {
            "low": "Use concise, low-reasoning behavior. Keep planning shallow and avoid long chains of internal reasoning or over-explaining. Prefer quick direct answers and minimal tool use unless the task clearly needs more work.",
            "medium": "Use balanced reasoning and moderate tool use. Take enough care to complete the task accurately without overdoing it.",
            "high": "Use deeper reasoning and inspect context carefully before acting. Spend more effort on planning and verification when the task is ambiguous or complex.",
            "max": "Use the deepest reasoning available. Inspect evidence thoroughly, verify assumptions, and be highly deliberate before editing or answering.",
        }.get(effort_name, "Use balanced reasoning and moderate tool use.")
        base_system_instruction = (
            f"[CURRENT DATE/TIME] Today is {current_date_str}. The current local time is {current_time_str}. "
            f"The current year is {now.year}. Use this date when interpreting words like latest, newest, recent, today, this year, or upcoming.\n"
            f"If the user asks a factual question about a movie, show, book, release, news item, person, or event, answer that question directly. Do not create scripts, games, apps, or workspace files unless the user explicitly asks you to build or edit an artifact.\n"
            f"{effort_instruction}\n"
            f"Answer naturally and keep simple replies fast. For links, prefer markdown links with readable titles, like [Site Name - Page Title](https://example.com/page), not bare URLs.\n"
        )
        is_first_user_turn = len([m for m in messages if m["role"] == "user"]) <= 1
        title_instruction = (
            "This is the first user turn in this chat. Before your visible answer, output exactly one hidden tag "
            "<chat_title>Short Topic Name</chat_title> with a concise 2-5 word topic you infer this chat is about. "
            "Do not mention the title tag in the visible answer.\n"
            if is_first_user_turn else ""
        )
        search_tool_instruction = (
            "You have a hidden web search tool. Only use it if you strictly need fresh, real-time, or current factual information that requires looking up (e.g., current news, recent events, or specific real-time facts).\n"
            "If the user explicitly asks you to search, browse, look up, find news, use the web, or answer with latest/current/recent information, you MUST use <search> before answering.\n"
            "CRITICAL: If you are asked about the existence, status, or news of a movie, software, book, release, person, event, or any factual claim, and you do not know about it or are about to say 'there is no official adaptation/release' or 'I don't know', you MUST first silently use your web search tool (<search>query</search>) to verify it. Do NOT guess or confidently state that something does not exist without searching first!\n"
            "Do NOT use web search for general knowledge, math, programming, simple greetings, or standard reasoning.\n"
            "If you strictly require a web search in normal chat, silently output exactly <search>short focused query</search> and nothing else for that turn. In agent/workspace mode, the highest-priority status rule still applies: emit a specific <status>...</status> immediately before <search>.\n"
            "Never mention searches, APIs, or internal uncertainty in the visible answer.\n"
        )
        image_tool_instruction = (
            "When the user asks for images, asks what something looks like, or visuals would clearly improve the answer, "
            "silently output exactly <image_search>short visual query</image_search>. Choose the query from the user's intent. "
            "Do not write bracketed tool labels, API names, or say that you are searching. If you also answer in text, keep it natural; the app may place chosen images below your answer.\n"
        )
        agent_system_instruction = (
            f"{base_system_instruction}"
            f"{title_instruction}"
            f"{search_tool_instruction if req.searchWeb else ''}"
            f"{image_tool_instruction}"
            f"{proactive_instruction}"
            f"{personal_intelligence}\n"
            f"{skills_instruction}\n"
            f"{sandbox_instruction}"
        )
        if req.systemPrompt:
            agent_system_instruction += req.systemPrompt.strip() + "\n"
        fast_system_instruction = base_system_instruction + title_instruction + (search_tool_instruction if req.searchWeb else "") + image_tool_instruction
        if req.systemPrompt:
            fast_system_instruction += req.systemPrompt.strip() + "\n"
        system_instruction = agent_system_instruction if workspace_context_needed else fast_system_instruction

        system_msg = next((m for m in messages if m["role"] == "system"), None)
        if system_msg:
            system_msg["content"] = system_instruction + "\n" + system_msg["content"]
        else:
            messages.insert(0, {"role": "system", "content": system_instruction})
        turn_max_tokens = generation_token_budget(workspace_context_needed)

        clean_model = req.model.replace("-thinking", "").replace("thinking", "").strip()

        # Check available local models
        local_model_names = set()
        p_dir = Path(model_dir)
        if p_dir.exists() and p_dir.is_dir():
            local_model_names.update({"geocentric-local", "geocentric-raw", "geocentric-local-thinking"})
        for folder in ["models", "runs"]:
            p = Path(folder)
            if p.exists() and p.is_dir():
                for path in p.rglob("*"):
                    if path.is_dir():
                        if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                            local_model_names.add(str(path.relative_to(p)))

        # Fetch Ollama models
        ollama_models = []
        try:
            ollama_models = await asyncio.to_thread(get_ollama_models)
        except Exception:
            pass

        # Determine Ollama vs Local
        is_ollama_model = False
        matched_ollama_model = clean_model

        if clean_model not in local_model_names:
            if clean_model in ollama_models or any(clean_model in m for m in ollama_models) or len(ollama_models) > 0:
                is_ollama_model = True
                matched_ollama_model = get_ollama_model_for_mode(is_instant, clean_model)

        if is_ollama_model:
            ollama_model_name = matched_ollama_model
            print(f"Proxying request to local Ollama service for model: {ollama_model_name}")
            base_url = "http://127.0.0.1:11434/v1/chat/completions"

            # Prepend search tool instructions so the model can invoke searches when needed
            current_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
            preplanned_image_query = ""

            def ollama_chat_once(messages_payload: list[dict[str, str]], max_tokens: int = 384, temperature: float = 0.0) -> str:
                payload = {
                    "model": ollama_model_name,
                    "messages": messages_payload,
                    "stream": False,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                req_http = urllib.request.Request(
                    base_url,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req_http, timeout=45) as response:
                    res_data = json.loads(response.read().decode())
                return res_data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""

            def parse_tool_plan(plan_text: str) -> dict[str, Any]:
                plan_src = (plan_text or "").strip()
                json_match = re.search(r"\{[\s\S]*\}", plan_src)
                if json_match:
                    plan_src = json_match.group(0)
                try:
                    plan = json.loads(plan_src)
                except Exception:
                    return {"web_search_queries": [], "image_search_query": ""}
                queries = plan.get("web_search_queries") or []
                if isinstance(queries, str):
                    queries = [queries]
                queries = [
                    re.sub(r"\s+", " ", str(query)).strip()[:160]
                    for query in queries
                    if str(query).strip()
                ][:3]
                image_query = clean_image_query(str(plan.get("image_search_query") or ""))[:120].strip()
                return {"web_search_queries": queries, "image_search_query": image_query}

            def search_context_for_queries(queries: list[str]) -> str:
                blocks = []
                seen_urls = set()
                for query in queries[:3]:
                    results = search_duckduckgo(query, max_results=5)
                    if not results:
                        blocks.append(f"[SEARCH QUERY: {query}]\nNo results found.")
                        continue
                    lines = []
                    for result in results:
                        url = result.get("url", "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        lines.append(
                            f"- Source: {result.get('title', '').strip()} ({url})\n"
                            f"  Snippet: {result.get('snippet', '').strip()}"
                        )
                    if lines:
                        blocks.append(f"[SEARCH QUERY: {query}]\n" + "\n".join(lines))
                if not blocks:
                    return ""
                return (
                    "\n[HIDDEN WEB CONTEXT]\n"
                    "Use these current web results to answer the user's exact question. "
                    "If they are not enough, silently request another <search> query. "
                    "Cite useful sources with readable markdown links.\n"
                    + "\n\n".join(blocks)
                    + "\n[/HIDDEN WEB CONTEXT]\n"
                )

            def run_hidden_tool_planner() -> None:
                nonlocal current_messages, preplanned_image_query
                if not req.searchWeb:
                    return
                if workspace_context_needed:
                    return
                latest_user = latest_user_text(current_messages)
                if not latest_user.strip():
                    return
                planner_system = (
                    "You are a hidden tool planner for a chat assistant. Decide if web search or image search tools are strictly required to answer the user's request. "
                    "Output only valid compact JSON with keys web_search_queries and image_search_query.\n"
                    "CRITICAL: If the user asks about the existence, status, or recent news of a movie, book, release, person, software, or event, or makes a factual claim that might have changed, you MUST run a search query to check it. Never return empty searches if you might say 'there isn't one' or 'I don't know' without verifying first!\n"
                    "Otherwise, be conservative: Do NOT use web search for general knowledge, math, programming/code, explanations, simple greetings, chitchat, or advice.\n"
                    "If no search tool is strictly needed, use empty values."
                )
                planner_user = (
                    f"Current date: {current_date_str}. User request:\n{latest_user}\n\n"
                    'Return JSON only, like {"web_search_queries":["query one"],"image_search_query":"query or empty string"}.'
                )
                try:
                    plan_text = ollama_chat_once(
                        [
                            {"role": "system", "content": planner_system},
                            {"role": "user", "content": planner_user},
                        ],
                        max_tokens=256,
                        temperature=0.0,
                    )
                    plan = parse_tool_plan(plan_text)
                    context = search_context_for_queries(plan["web_search_queries"])
                    if context:
                        current_messages.append({"role": "user", "content": context})
                    preplanned_image_query = plan["image_search_query"]
                except Exception as planner_exc:
                    print(f"Hidden tool planner failed: {planner_exc}")

            await asyncio.to_thread(run_hidden_tool_planner)
            if req.stream:
                async def event_stream_ollama():
                    nonlocal current_messages
                    turn_limit = continuation_turn_limit(workspace_context_needed)
                    consecutive_toolless_turns = 0
                    for turn_idx in range(turn_limit):
                        has_more_turns = turn_idx + 1 < turn_limit
                        workspace_tools_required = workspace_context_needed and workspace_artifacts_requested
                        payload = {
                            "model": ollama_model_name,
                            "messages": current_messages,
                            "stream": True,
                            "stream_options": {"include_usage": True},
                            "max_tokens": turn_max_tokens,
                            "temperature": 0.7
                        }
                        req_http = urllib.request.Request(
                            base_url,
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"}
                        )

                        accumulated = ""
                        has_search = False
                        search_query = ""
                        finish_reason = ""
                        last_stream_progress = ""

                        # Console tracking for real-time terminal output (debug only)
                        in_reasoning = False

                        try:
                            # We wrap this block so we can read the response in chunk segments
                            response = await asyncio.to_thread(urllib.request.urlopen, req_http)
                            while True:
                                line = await asyncio.to_thread(response.readline)
                                if not line:
                                    break
                                if line:
                                        decoded_line = line.decode()
                                        if decoded_line.startswith("data:"):
                                            data_str = decoded_line.replace("data:", "").strip()
                                            if data_str == "[DONE]":
                                                break
                                            try:
                                                chunk = json.loads(data_str)
                                                choice = chunk.get("choices", [{}])[0]
                                                delta = choice.get("delta", {})
                                                finish_reason = choice.get("finish_reason") or finish_reason
                                                content = delta.get("content", "")
                                                reasoning_content = delta.get("reasoning_content", "")

                                                if reasoning_content:
                                                    if not in_reasoning:
                                                        in_reasoning = True
                                                    _server_stream_write(reasoning_content)

                                                if content:
                                                    if in_reasoning:
                                                        in_reasoning = False
                                                    _server_stream_write(content)

                                                accumulated += content
                                                usage_payload = extract_usage_payload(chunk)

                                                # Intercept search command in real-time
                                                if "<search" in accumulated.lower() or "[search]" in accumulated.lower() or "call:search" in accumulated.lower():
                                                    has_search = True
                                                    if workspace_context_needed:
                                                        _, seen_statuses = extract_status_tags(accumulated)
                                                        progress = seen_statuses[-1] if seen_statuses else ""
                                                        if progress and progress != last_stream_progress:
                                                            last_stream_progress = progress
                                                            yield sse_chunk(f"<status>{progress}</status>")
                                                    if "</search>" in accumulated.lower() or "[/search]" in accumulated.lower() or ("call:search" in accumulated.lower() and "}" in accumulated.lower()):
                                                        search_query = extract_web_search_query(accumulated)
                                                        break
                                                    continue # Buffer search command, do not stream to user

                                                if workspace_context_needed:
                                                    progress = ""
                                                    _, seen_statuses = extract_status_tags(accumulated)
                                                    if seen_statuses:
                                                        progress = seen_statuses[-1]
                                                    else:
                                                        progress = extract_tool_progress_event(accumulated)
                                                    if progress and progress != last_stream_progress:
                                                        last_stream_progress = progress
                                                        yield sse_chunk(f"<status>{progress}</status>", usage=usage_payload)
                                                else:
                                                    yield sse_chunk(content, reasoning_content, usage=usage_payload)
                                            except Exception:
                                                pass
                                        await asyncio.sleep(0.001)
                        except Exception as exc:
                            in_reasoning = False
                            yield sse_chunk(f"Ollama stream error: {str(exc)}")
                            break

                        in_reasoning = False

                        if has_search and search_query:
                            if req.searchWeb:
                                print(f"Model requested web search: '{search_query}'")
                                search_results = await asyncio.to_thread(search_duckduckgo, search_query)
                                if search_results:
                                    context_str = "\n".join([
                                        f"- Source: {r['title']} ({r['url']})\n  Snippet: {r['snippet']}"
                                        for r in search_results
                                    ])
                                    web_context = (
                                        f"\n[REAL-TIME SEARCH RESULTS FOR '{search_query}']\n"
                                        f"{context_str}\n\n"
                                        f"Please use these search results to answer the user's question completely. Cite sources with readable markdown links like [Website - Page Title](URL), not bare URLs."
                                    )
                                    current_messages.append({"role": "assistant", "content": f"<search>{search_query}</search>"})
                                    current_messages.append({"role": "user", "content": web_context})
                                    continue
                                else:
                                    current_messages.append({"role": "assistant", "content": f"<search>{search_query}</search>"})
                                    current_messages.append({"role": "user", "content": "\n[SYSTEM: No search results found. Please reply without search context.]"})
                                    continue
                            else:
                                current_messages.append({"role": "assistant", "content": f"<search>{search_query}</search>"})
                                current_messages.append({"role": "user", "content": "\n[SYSTEM: Web search is disabled. Please reply directly without searching.]"})
                                continue

                        if (finish_reason == "length" or response_looks_truncated(accumulated)) and has_more_turns:
                            current_messages.append({"role": "assistant", "content": accumulated})
                            unclosed_tag = find_unclosed_tag(accumulated)
                            if unclosed_tag:
                                continuation_instruction = (
                                    f"<status>Compacting context after the model hit its token limit; resuming inside tag <{unclosed_tag}>.</status>\n"
                                    f"[SYSTEM FEEDBACK: The previous response was cut off inside the <{unclosed_tag}> tag.]\n"
                                    f"Continue exactly where you stopped inside the <{unclosed_tag}> tag. Do NOT repeat the opening tag, do NOT restart, do NOT summarize, and do NOT repeat anything you already wrote. Resume typing the content immediately:"
                                )
                            else:
                                continuation_instruction = (
                                    "<status>Compacting context after the model hit its token limit; continuing from the cutoff.</status>\n"
                                    "[SYSTEM FEEDBACK: The previous response was cut off before the workspace task was complete.]\n"
                                    "Continue exactly where you stopped. Do NOT repeat anything you already wrote, do NOT restart, do NOT summarize, and resume typing the content immediately:"
                                )
                            current_messages.append({
                                "role": "user",
                                "content": continuation_instruction,
                            })
                            current_messages = compact_agent_messages(current_messages)
                            continue

                        if workspace_tools_required and not workspace_tool_tags_present(accumulated):
                            if has_more_turns:
                                consecutive_toolless_turns += 1
                                if consecutive_toolless_turns >= 2:
                                    break
                                current_messages.append({"role": "assistant", "content": accumulated})
                                current_messages.append({
                                    "role": "user",
                                    "content": (
                                        "[SYSTEM FEEDBACK: This request requires real workspace execution, but you did not use any workspace tools.]\n"
                                        "First emit a specific <status> update, then start over using tool tags only for the implementation phase. Create a project folder with <run_command>mkdir -p ...</run_command>, write files with <write_file>, and verify with <run_command>, <run_file>, or <agent_terminal>. Do not paste the project source into chat."
                                    ),
                                })
                                continue
                        else:
                            consecutive_toolless_turns = 0

                        claim_correction = inject_tool_claim_correction(accumulated, accumulated)
                        if claim_correction and workspace_context_needed:
                            yield sse_chunk(f"<status>{render_status_banner('Correcting tool invocation')}</status>")
                            current_messages.append({"role": "assistant", "content": accumulated})
                            current_messages.append({"role": "user", "content": claim_correction})
                            continue

                        # Process sandbox workspace tags if user is signed in
                        run_result = None
                        if user and workspace_context_needed:
                            import queue as py_queue
                            status_queue = py_queue.Queue()
                            loop = asyncio.get_running_loop()

                            def on_status_update(status_text: str):
                                loop.call_soon_threadsafe(status_queue.put, f"<status>{status_text}</status>")

                            def run_sandbox():
                                try:
                                    return process_sandbox_tags(user["id"], req.conversationId, accumulated, on_status_update)
                                except Exception as e:
                                    print(f"Error in sandbox tags execution thread: {e}")
                                    return f"ERROR executing tools: {str(e)}"

                            thread_res = {}
                            def run_sandbox_wrapper():
                                thread_res["result"] = run_sandbox()

                            sandbox_thread = threading.Thread(target=run_sandbox_wrapper, daemon=True)
                            sandbox_thread.start()

                            while sandbox_thread.is_alive() or not status_queue.empty():
                                try:
                                    status_item = status_queue.get_nowait()
                                    yield sse_chunk(status_item)
                                except py_queue.Empty:
                                    await asyncio.sleep(0.05)

                            run_result = thread_res.get("result")

                        if run_result:
                            is_error = sandbox_execution_needs_correction(run_result)
                            feedback_target = sandbox_feedback_target(run_result)
                            if is_error:
                                yield sse_chunk(code_execution_retry_status(feedback_target))
                                current_messages.append({"role": "assistant", "content": accumulated})
                                feedback = f"[SYSTEM FEEDBACK: Code Execution Error while running {feedback_target}]\n{run_result}\n{sandbox_feedback_instruction(run_result)}"
                                current_messages.append({"role": "user", "content": feedback})
                                continue
                            else:
                                if workspace_tools_required:
                                    needs_more, missing = workspace_completion_status(
                                        turn_text=accumulated,
                                        all_messages=current_messages,
                                        latest_user_message=latest_user_message_content,
                                        workspace_tools_required=workspace_tools_required,
                                        run_result=run_result,
                                    )
                                    if needs_more and has_more_turns:
                                        current_messages.append({"role": "assistant", "content": accumulated})
                                        current_messages.append({
                                            "role": "user",
                                            "content": (
                                                "[SYSTEM FEEDBACK: Workspace tool results]\n"
                                                f"{run_result}\n\n"
                                                "The task is not complete yet. First emit a specific <status> update, then "
                                                + " and ".join(missing)
                                                + ". Continue with the next concrete workspace tool calls and then summarize only after verification succeeds."
                                            ),
                                        })
                                        continue
                                else:
                                    yield sse_chunk(f"\n\n[Workspace Result]\n{run_result}\n")

                        if workspace_context_needed:
                            visible_reply = strip_agent_progress_notices(strip_internal_tags(accumulated))
                            if not visible_reply and user:
                                _, visible_statuses = extract_status_tags(accumulated)
                                visible_reply = synthesize_completion_reply(user["id"], req.conversationId, visible_statuses)
                            if visible_reply:
                                yield sse_chunk(visible_reply)

                        usage_payload = build_usage_payload(max(1, len(prompt) // 4), max(1, len(accumulated) // 4))
                        yield sse_chunk("", "", usage=usage_payload)

                        # Fetch and append images if the model requested image search explicitly OR user explicitly wants images
                        image_query = extract_image_search_query(accumulated)
                        if not image_query and user_wants_images(latest_user_text(current_messages)):
                            image_query = preplanned_image_query or latest_user_image_query(current_messages)
                        images_text = image_gallery_block(image_query)
                        if images_text:
                            yield sse_chunk(images_text)
                        for meta_chunk in stream_hidden_metadata_chunks(accumulated):
                            yield meta_chunk
                        break
                    yield "data: [DONE]\n\n"

                return StreamingResponse(event_stream_ollama(), media_type="text/event-stream")
            else:
                try:
                    turn_limit = continuation_turn_limit(workspace_context_needed)
                    consecutive_toolless_turns = 0
                    for turn_idx in range(turn_limit):
                        has_more_turns = turn_idx + 1 < turn_limit
                        workspace_tools_required = workspace_context_needed and workspace_artifacts_requested
                        payload = {
                            "model": ollama_model_name,
                            "messages": current_messages,
                            "stream": False,
                            "stream_options": {"include_usage": True},
                            "max_tokens": turn_max_tokens,
                            "temperature": 0.7
                        }
                        req_http = urllib.request.Request(
                            base_url,
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"}
                        )
                        def fetch_res():
                            with urllib.request.urlopen(req_http) as response:
                                return json.loads(response.read().decode())
                        res_data = await asyncio.to_thread(fetch_res)
                        choice = res_data.get("choices", [{}])[0]
                        message = choice.get("message", {})
                        text = message.get("content", "")
                        reasoning_content = message.get("reasoning_content", "")
                        finish_reason = choice.get("finish_reason") or ""

                        search_query = extract_web_search_query(text)
                        if search_query:
                            if req.searchWeb:
                                print(f"Model requested web search: '{search_query}'")
                                search_results = await asyncio.to_thread(search_duckduckgo, search_query)
                                if search_results:
                                    context_str = "\n".join([
                                        f"- Source: {r['title']} ({r['url']})\n  Snippet: {r['snippet']}"
                                        for r in search_results
                                    ])
                                    web_context = (
                                        f"\n[REAL-TIME SEARCH RESULTS FOR '{search_query}']\n"
                                        f"{context_str}\n\n"
                                        f"Please use these search results to answer the user's question completely. Cite sources with readable markdown links like [Website - Page Title](URL), not bare URLs."
                                    )
                                    current_messages.append({"role": "assistant", "content": f"<search>{search_query}</search>"})
                                    current_messages.append({"role": "user", "content": web_context})
                                    continue
                                else:
                                    current_messages.append({"role": "assistant", "content": f"<search>{search_query}</search>"})
                                    current_messages.append({"role": "user", "content": "\n[SYSTEM: Web search is disabled. Please reply directly without searching.]"})
                                    continue

                            if (finish_reason == "length" or response_looks_truncated(text)) and has_more_turns:
                                current_messages.append({"role": "assistant", "content": text})
                                unclosed_tag = find_unclosed_tag(text)
                                if unclosed_tag:
                                    continuation_instruction = (
                                        f"<status>Compacting context after the model hit its token limit; resuming inside tag <{unclosed_tag}>.</status>\n"
                                        f"[SYSTEM FEEDBACK: The previous response was cut off inside the <{unclosed_tag}> tag.]\n"
                                        f"Continue exactly where you stopped inside the <{unclosed_tag}> tag. Do NOT repeat the opening tag, do NOT restart, do NOT summarize, and do NOT repeat anything you already wrote. Resume typing the content immediately:"
                                    )
                                else:
                                    continuation_instruction = (
                                        "<status>Compacting context after the model hit its token limit; continuing from the cutoff.</status>\n"
                                        "[SYSTEM FEEDBACK: The previous response was cut off before completion.]\n"
                                        "Continue exactly where you stopped. Do NOT repeat anything you already wrote, do NOT restart, do NOT summarize, and resume typing the content immediately:"
                                    )
                                current_messages.append({
                                    "role": "user",
                                    "content": continuation_instruction,
                                })
                                current_messages = compact_agent_messages(current_messages)
                                continue

                            if workspace_tools_required and not workspace_tool_tags_present(text):
                                if has_more_turns:
                                    consecutive_toolless_turns += 1
                                    if consecutive_toolless_turns >= 2:
                                        break
                                    current_messages.append({"role": "assistant", "content": text})
                                    current_messages.append({
                                        "role": "user",
                                        "content": (
                                            "[SYSTEM FEEDBACK: This workspace request requires real tool execution, but you did not use workspace tools.]\n"
                                            "Use <run_command>, <write_file>, and a verification command now. Do not paste source code into chat."
                                        ),
                                    })
                                    continue
                            else:
                                consecutive_toolless_turns = 0

                            # Process sandbox workspace tags
                            run_result = None
                            if user and workspace_context_needed:
                                run_result = process_sandbox_tags(user["id"], req.conversationId, text)

                            if run_result:
                                is_error = sandbox_execution_needs_correction(run_result)
                                feedback_target = sandbox_feedback_target(run_result)
                                if is_error:
                                    current_messages.append({"role": "assistant", "content": text})
                                    feedback = f"[SYSTEM FEEDBACK: Code Execution Error while running {feedback_target}]\n{run_result}\n{sandbox_feedback_instruction(run_result)}"
                                    current_messages.append({"role": "user", "content": feedback})
                                    continue
                                else:
                                    if workspace_tools_required:
                                        needs_more, missing = workspace_completion_status(
                                            turn_text=text,
                                            all_messages=current_messages,
                                            latest_user_message=latest_user_message_content,
                                            workspace_tools_required=workspace_tools_required,
                                            run_result=run_result,
                                        )
                                        if needs_more and has_more_turns:
                                            current_messages.append({"role": "assistant", "content": text})
                                            current_messages.append({
                                                "role": "user",
                                                "content": (
                                                    "[SYSTEM FEEDBACK: Workspace tool results]\n"
                                                    f"{run_result}\n\n"
                                                    "Continue: you must "
                                                    + " and ".join(missing)
                                                    + " before the task can be considered complete."
                                                ),
                                            })
                                            continue
                                    else:
                                        text += f"\n\n[Workspace Result]\n{run_result}"


                            usage_payload = extract_usage_payload(res_data) or build_usage_payload(max(1, len(prompt) // 4), max(1, len(text) // 4))
                            res_dict = {"reply": text, "usage": usage_payload}
                            if reasoning_content:
                                res_dict["reasoning"] = reasoning_content

                            # Fetch and append images to reply if the model explicitly requested it OR user explicitly wants images
                            image_query = extract_image_search_query(text)
                            if not image_query and user_wants_images(latest_user_text(current_messages)):
                                image_query = preplanned_image_query or latest_user_image_query(current_messages)
                            res_dict["reply"] += image_gallery_block(image_query)
                            return res_dict
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"Ollama proxy error: {str(exc)}")

        # Load the selected local model or fallback to cli_model/geocentric-local
        try:
            model_name = clean_model
            if model_name not in local_model_names:
                model_name = cli_model or "geocentric-local"
            print(f"Selecting local model: {model_name}")
            model, tokenizer = get_model_and_tokenizer(model_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load local model: {str(e)}")

        current_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        if req.stream:
            async def event_stream():
                nonlocal current_messages
                turn_limit = continuation_turn_limit(workspace_context_needed)
                consecutive_toolless_turns = 0
                for turn_idx in range(turn_limit):
                    has_more_turns = turn_idx + 1 < turn_limit
                    workspace_tools_required = workspace_context_needed and workspace_artifacts_requested
                    system = next((m["content"] for m in current_messages if m["role"] == "system"), "")

                    is_gemma = False
                    try:
                        target_path = Path(model_dir)
                        if "gemma" in str(target_path).lower():
                            is_gemma = True
                    except Exception:
                        pass

                    if is_gemma:
                        prompt = ""
                        if system:
                            prompt += f"<start_of_turn>system\n{system}<end_of_turn>\n"
                        for msg in current_messages:
                            role = msg.get("role", "user")
                            content = msg.get("content", "").strip()
                            if not content or role == "system":
                                continue
                            if role == "user":
                                prompt += f"<start_of_turn>user\n{content}<end_of_turn>\n"
                            elif role == "assistant":
                                prompt += f"<start_of_turn>model\n{content}<end_of_turn>\n"
                        prompt += "<start_of_turn>model\n"
                    elif hasattr(tokenizer, "apply_chat_template"):
                        try:
                            prompt = tokenizer.apply_chat_template(current_messages, tokenize=False, add_generation_prompt=True)
                        except Exception as exc:
                            print(f"⚠️ apply_chat_template failed: {exc}")
                            prompt = build_chat_prompt(current_messages, system=system)
                    else:
                        prompt = build_chat_prompt(current_messages, system=system)

                    any_token = False
                    accumulated_text = ""
                    last_stream_progress = ""
                    q = run_generator_in_thread(
                        stream_text,
                        model=model,
                        tokenizer=tokenizer,
                        prompt=prompt,
                        device=device,
                        max_new_tokens=turn_max_tokens,
                        temperature=0.7,
                        top_k=50,
                        repetition_penalty=1.15,
                    )
                    async for token in async_generator_from_queue(q):
                        any_token = True
                        accumulated_text += token
                        _server_stream_write(token)
                        if workspace_context_needed:
                            progress = ""
                            _, seen_statuses = extract_status_tags(accumulated_text)
                            if seen_statuses:
                                progress = seen_statuses[-1]
                            else:
                                progress = extract_tool_progress_event(accumulated_text)
                            if progress and progress != last_stream_progress:
                                last_stream_progress = progress
                                yield sse_chunk(f"<status>{progress}</status>")
                        await asyncio.sleep(0.005)
                    if not any_token:
                        yield sse_chunk("I trained in the cloud, but I need more data or training steps to answer well yet.")
                        break

                    has_search = False
                    search_query = ""
                    if "<search" in accumulated_text.lower() or "[search]" in accumulated_text.lower() or "call:search" in accumulated_text.lower():
                        has_search = True
                        if workspace_context_needed:
                            _, seen_statuses = extract_status_tags(accumulated_text)
                            progress = seen_statuses[-1] if seen_statuses else ""
                            if progress and progress != last_stream_progress:
                                last_stream_progress = progress
                                yield sse_chunk(f"<status>{progress}</status>")
                        if "</search>" in accumulated_text.lower() or "[/search]" in accumulated_text.lower() or ("call:search" in accumulated_text.lower() and "}" in accumulated_text.lower()):
                            search_query = extract_web_search_query(accumulated_text)

                    if has_search and search_query:
                        if req.searchWeb:
                            print(f"Local model requested web search: '{search_query}'")
                            search_results = await asyncio.to_thread(search_duckduckgo, search_query)
                            if search_results:
                                context_str = "\n".join([
                                    f"- Source: {r['title']} ({r['url']})\n  Snippet: {r['snippet']}"
                                    for r in search_results
                                ])
                                web_context = (
                                    f"\n[REAL-TIME SEARCH RESULTS FOR '{search_query}']\n"
                                    f"{context_str}\n\n"
                                    f"Please use these search results to answer the user's question completely. Cite sources with readable markdown links like [Website - Page Title](URL), not bare URLs."
                                )
                                current_messages.append({"role": "assistant", "content": accumulated_text})
                                current_messages.append({"role": "user", "content": web_context})
                                continue
                            else:
                                current_messages.append({"role": "assistant", "content": accumulated_text})
                                current_messages.append({"role": "user", "content": "\n[SYSTEM: No search results found. Please reply without search context.]"})
                                continue
                        else:
                            current_messages.append({"role": "assistant", "content": accumulated_text})
                            current_messages.append({"role": "user", "content": "\n[SYSTEM: Web search is disabled. Please reply directly without searching.]"})
                            continue

                    if response_looks_truncated(accumulated_text) and has_more_turns:
                        current_messages.append({"role": "assistant", "content": accumulated_text})
                        unclosed_tag = find_unclosed_tag(accumulated_text)
                        if unclosed_tag:
                            continuation_instruction = (
                                f"<status>Compacting context after the model hit its token limit; resuming inside tag <{unclosed_tag}>.</status>\n"
                                f"[SYSTEM FEEDBACK: The previous response was cut off inside the <{unclosed_tag}> tag.]\n"
                                f"Continue exactly where you stopped inside the <{unclosed_tag}> tag. Do NOT repeat the opening tag, do NOT restart, do NOT summarize, and do NOT repeat anything you already wrote. Resume typing the content immediately:"
                            )
                        else:
                            continuation_instruction = (
                                "<status>Compacting context after the model hit its token limit; continuing from the cutoff.</status>\n"
                                "[SYSTEM FEEDBACK: The previous response was cut off before completion.]\n"
                                "Continue exactly where you stopped. Do NOT repeat anything you already wrote, do NOT restart, do NOT summarize, and resume typing the content immediately:"
                            )
                        current_messages.append({
                            "role": "user",
                            "content": continuation_instruction,
                        })
                        current_messages = compact_agent_messages(current_messages)
                        continue

                    if workspace_tools_required and not workspace_tool_tags_present(accumulated_text):
                        if has_more_turns:
                            consecutive_toolless_turns += 1
                            if consecutive_toolless_turns >= 2:
                                break
                            current_messages.append({"role": "assistant", "content": accumulated_text})
                            current_messages.append({
                                "role": "user",
                                "content": (
                                    "[SYSTEM FEEDBACK: This request requires real workspace execution, but you did not use any workspace tools.]\n"
                                    "First emit a specific <status> update, then use <run_command>, <write_file>, and a verification command now. Do not paste source code into chat."
                                ),
                            })
                            continue
                    else:
                        consecutive_toolless_turns = 0

                    visible_accumulated_text = strip_internal_tags(accumulated_text)
                    if visible_accumulated_text and not workspace_context_needed:
                        yield sse_chunk(visible_accumulated_text)

                    run_result = None
                    if user and workspace_context_needed:
                        import queue as py_queue
                        status_queue = py_queue.Queue()
                        loop = asyncio.get_running_loop()

                        def on_status_update(status_text: str):
                            loop.call_soon_threadsafe(status_queue.put, f"<status>{status_text}</status>")

                        def run_sandbox():
                            try:
                                return process_sandbox_tags(user["id"], req.conversationId, accumulated_text, on_status_update)
                            except Exception as e:
                                print(f"Error in sandbox tags execution thread: {e}")
                                return f"ERROR executing tools: {str(e)}"

                        thread_res = {}
                        def run_sandbox_wrapper():
                            thread_res["result"] = run_sandbox()

                        sandbox_thread = threading.Thread(target=run_sandbox_wrapper, daemon=True)
                        sandbox_thread.start()

                        while sandbox_thread.is_alive() or not status_queue.empty():
                            try:
                                status_item = status_queue.get_nowait()
                                yield sse_chunk(status_item)
                            except py_queue.Empty:
                                await asyncio.sleep(0.05)

                        run_result = thread_res.get("result")

                    if run_result:
                        is_error = sandbox_execution_needs_correction(run_result)
                        feedback_target = sandbox_feedback_target(run_result)
                        if is_error:
                            yield sse_chunk(code_execution_retry_status(feedback_target))
                            current_messages.append({"role": "assistant", "content": accumulated_text})
                            feedback = f"[SYSTEM FEEDBACK: Code Execution Error while running {feedback_target}]\n{run_result}\n{sandbox_feedback_instruction(run_result)}"
                            current_messages.append({"role": "user", "content": feedback})
                            continue
                        else:
                            if workspace_tools_required:
                                needs_more, missing = workspace_completion_status(
                                    turn_text=accumulated_text,
                                    all_messages=current_messages,
                                    latest_user_message=latest_user_message_content,
                                    workspace_tools_required=workspace_tools_required,
                                    run_result=run_result,
                                )
                                if needs_more and has_more_turns:
                                    current_messages.append({"role": "assistant", "content": accumulated_text})
                                    current_messages.append({
                                        "role": "user",
                                        "content": (
                                            "[SYSTEM FEEDBACK: Workspace tool results]\n"
                                            f"{run_result}\n\n"
                                            "Continue: first emit a specific <status> update, then "
                                            + " and ".join(missing)
                                            + " before the task can be considered complete."
                                        ),
                                    })
                                    continue
                            else:
                                yield sse_chunk(f"\n\n[Workspace Result]\n{run_result}\n")

                    if workspace_context_needed:
                        visible_accumulated_text = strip_agent_progress_notices(visible_accumulated_text)
                        if not visible_accumulated_text and user:
                            _, visible_statuses = extract_status_tags(accumulated_text)
                            visible_accumulated_text = synthesize_completion_reply(user["id"], req.conversationId, visible_statuses)
                        if visible_accumulated_text:
                            yield sse_chunk(visible_accumulated_text)

                    image_query = extract_image_search_query(accumulated_text)
                    if not image_query and user_wants_images(latest_user_text(current_messages)):
                        image_query = latest_user_image_query(current_messages)
                    images_text = image_gallery_block(image_query)
                    if images_text:
                        yield sse_chunk(images_text)
                    for meta_chunk in stream_hidden_metadata_chunks(accumulated_text):
                        yield meta_chunk
                    break
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")
        else:
            text = ""
            turn_limit = continuation_turn_limit(workspace_context_needed)
            consecutive_toolless_turns = 0
            for turn_idx in range(turn_limit):
                has_more_turns = turn_idx + 1 < turn_limit
                workspace_tools_required = workspace_context_needed and workspace_artifacts_requested
                system = next((m["content"] for m in current_messages if m["role"] == "system"), "")

                is_gemma = False
                try:
                    target_path = Path(model_dir)
                    if "gemma" in str(target_path).lower():
                        is_gemma = True
                except Exception:
                    pass

                if is_gemma:
                    prompt = ""
                    if system:
                        prompt += f"<start_of_turn>system\n{system}<end_of_turn>\n"
                    for msg in current_messages:
                        role = msg.get("role", "user")
                        content = msg.get("content", "").strip()
                        if not content or role == "system":
                            continue
                        if role == "user":
                            prompt += f"<start_of_turn>user\n{content}<end_of_turn>\n"
                        elif role == "assistant":
                            prompt += f"<start_of_turn>model\n{content}<end_of_turn>\n"
                    prompt += "<start_of_turn>model\n"
                elif hasattr(tokenizer, "apply_chat_template"):
                    try:
                        prompt = tokenizer.apply_chat_template(current_messages, tokenize=False, add_generation_prompt=True)
                    except Exception as exc:
                        print(f"⚠️ apply_chat_template failed: {exc}")
                        prompt = build_chat_prompt(current_messages, system=system)
                else:
                    prompt = build_chat_prompt(current_messages, system=system)

                turn_text = await asyncio.to_thread(
                    generate_text,
                    model=model,
                    tokenizer=tokenizer,
                    prompt=prompt,
                    device=device,
                    max_new_tokens=turn_max_tokens,
                    temperature=0.7,
                    top_k=50,
                    repetition_penalty=1.15,
                )

                has_search = False
                search_query = ""
                search_query = extract_web_search_query(turn_text)
                if search_query:
                    has_search = True

                if has_search and search_query:
                    if req.searchWeb:
                        print(f"Local model requested web search: '{search_query}'")
                        search_results = await asyncio.to_thread(search_duckduckgo, search_query)
                        if search_results:
                            context_str = "\n".join([
                                f"- Source: {r['title']} ({r['url']})\n  Snippet: {r['snippet']}"
                                for r in search_results
                            ])
                            web_context = (
                                f"\n[REAL-TIME SEARCH RESULTS FOR '{search_query}']\n"
                                f"{context_str}\n\n"
                                f"Please use these search results to answer the user's question completely. Cite sources with readable markdown links like [Website - Page Title](URL), not bare URLs."
                            )
                            current_messages.append({"role": "assistant", "content": turn_text})
                            current_messages.append({"role": "user", "content": web_context})
                            continue
                    else:
                        current_messages.append({"role": "assistant", "content": turn_text})
                        current_messages.append({"role": "user", "content": "\n[SYSTEM: Web search is disabled. Please reply directly without searching.]"})
                        continue

                if response_looks_truncated(turn_text) and has_more_turns:
                    current_messages.append({"role": "assistant", "content": turn_text})
                    unclosed_tag = find_unclosed_tag(turn_text)
                    if unclosed_tag:
                        continuation_instruction = (
                            f"<status>Compacting context after the model hit its token limit; resuming inside tag <{unclosed_tag}>.</status>\n"
                            f"[SYSTEM FEEDBACK: The previous response was cut off inside the <{unclosed_tag}> tag.]\n"
                            f"Continue exactly where you stopped inside the <{unclosed_tag}> tag. Do NOT repeat the opening tag, do NOT restart, do NOT summarize, and do NOT repeat anything you already wrote. Resume typing the content immediately:"
                        )
                    else:
                        continuation_instruction = (
                            "<status>Compacting context after the model hit its token limit; continuing from the cutoff.</status>\n"
                            "[SYSTEM FEEDBACK: The previous response was cut off before completion.]\n"
                            "Continue exactly where you stopped. Do NOT repeat anything you already wrote, do NOT restart, do NOT summarize, and resume typing the content immediately:"
                        )
                    current_messages.append({
                        "role": "user",
                        "content": continuation_instruction,
                    })
                    current_messages = compact_agent_messages(current_messages)
                    continue

                if workspace_tools_required and not workspace_tool_tags_present(turn_text):
                    if has_more_turns:
                        consecutive_toolless_turns += 1
                        if consecutive_toolless_turns >= 2:
                            break
                        current_messages.append({"role": "assistant", "content": turn_text})
                        current_messages.append({
                            "role": "user",
                            "content": (
                                "[SYSTEM FEEDBACK: This workspace request requires real tool execution, but you did not use workspace tools.]\n"
                                "Use <run_command>, <write_file>, and a verification command now. Do not paste source code into chat."
                            ),
                        })
                        continue
                else:
                    consecutive_toolless_turns = 0

                run_result = None
                if user and workspace_context_needed:
                    run_result = process_sandbox_tags(user["id"], req.conversationId, turn_text)

                if run_result:
                    is_error = sandbox_execution_needs_correction(run_result)
                    feedback_target = sandbox_feedback_target(run_result)
                    if is_error:
                        current_messages.append({"role": "assistant", "content": turn_text})
                        feedback = f"[SYSTEM FEEDBACK: Code Execution Error while running {feedback_target}]\n{run_result}\n{sandbox_feedback_instruction(run_result)}"
                        current_messages.append({"role": "user", "content": feedback})
                        continue
                    else:
                        if workspace_tools_required:
                            needs_more, missing = workspace_completion_status(
                                turn_text=turn_text,
                                all_messages=current_messages,
                                latest_user_message=latest_user_message_content,
                                workspace_tools_required=workspace_tools_required,
                                run_result=run_result,
                            )
                            if needs_more and has_more_turns:
                                current_messages.append({"role": "assistant", "content": turn_text})
                                current_messages.append({
                                    "role": "user",
                                    "content": (
                                        "[SYSTEM FEEDBACK: Workspace tool results]\n"
                                        f"{run_result}\n\n"
                                        "Continue: you must "
                                        + " and ".join(missing)
                                        + " before the task can be considered complete."
                                    ),
                                })
                                continue
                        else:
                            turn_text += f"\n\n[Workspace Result]\n{run_result}"


                text = turn_text
                image_query = extract_image_search_query(text)
                if not image_query and user_wants_images(latest_user_text(current_messages)):
                    image_query = latest_user_image_query(current_messages)
                text += image_gallery_block(image_query)
                break
            return {"reply": text}

    class AgentJobRequest:
        def __init__(self, token_value: str):
            self.headers = {"Authorization": f"Bearer {token_value}"} if token_value else {}
            self.client = type("Client", (), {"host": "127.0.0.1"})()

    def run_agent_job(job_id: str, user: Dict[str, Any], token_value: str, req: WebChatRequest):
        progress_lock = threading.Lock()
        progress_state = {"text": "", "at": time.time()}

        def check_cancelled() -> None:
            if agent_job_status(job_id) == "cancelled":
                raise AgentJobCancelled()

        def set_progress(text: str) -> None:
            check_cancelled()
            clean = re.sub(r"\s+", " ", str(text or "")).strip()
            if not clean:
                return
            with progress_lock:
                if clean == progress_state["text"] and time.time() - progress_state["at"] < 3:
                    return
                progress_state["text"] = clean
                progress_state["at"] = time.time()
            update_agent_job(job_id, progress=clean)

        try:
            update_agent_job(job_id, status="running", progress="Preparing workspace folder...")
            progress_state["text"] = "Preparing workspace folder..."

            workspace_dir = workspace_dir_for(user["id"], req.conversationId)
            workspace_dir.mkdir(parents=True, exist_ok=True)

            set_progress("Copying workspace templates...")
            copy_workspace_templates(workspace_dir)
            chat_messages = [m.model_dump() for m in req.messages]
            set_progress("Saving uploaded files into the workspace...")
            save_uploaded_attachments(user["id"], req.conversationId, chat_messages, req.attachments)
            job_has_attachments = bool(req.attachments) or any(m.get("attachments") for m in chat_messages)
            latest_job_user = latest_user_content(chat_messages)
            recent_job_context = "\n".join(
                str(m.get("content", "") or "")
                for m in chat_messages
                if m.get("role") == "user"
            )[-12_000:]
            workspace_task = (
                job_has_attachments
                or request_requires_workspace_artifacts(latest_job_user)
                or request_requires_workspace_artifacts(recent_job_context)
                or request_mentions_workspace(latest_job_user)
                or request_mentions_workspace(recent_job_context)
            )

            job_req = req.model_copy(deep=True)
            job_req.stream = True
            job_req.agentMode = bool(req.agentMode) or workspace_task

            async def collect_reply() -> str:
                set_progress("Preparing model prompt and tool instructions...")
                response = await web_chat(job_req, AgentJobRequest(token_value))
                if isinstance(response, StreamingResponse):
                    raw_reply = ""
                    last_progress = ""
                    last_stream_tick = time.time()
                    async for chunk in response.body_iterator:
                        check_cancelled()
                        if isinstance(chunk, bytes):
                            chunk = chunk.decode("utf-8", errors="ignore")
                        content_added = False
                        for packet in str(chunk).split("\n\n"):
                            for line in packet.splitlines():
                                if not line.startswith("data:"):
                                    continue
                                data_str = line.replace("data:", "", 1).strip()
                                if not data_str or data_str == "[DONE]":
                                    continue
                                try:
                                    parsed = json.loads(data_str)
                                    delta = parsed.get("choices", [{}])[0].get("delta", {})
                                    content_piece = delta.get("content", "")
                                    if content_piece:
                                        raw_reply += content_piece
                                        content_added = True
                                except Exception:
                                    raw_reply += data_str
                                    content_added = True
                        _, seen_statuses = extract_status_tags(raw_reply)
                        progress = seen_statuses[-1] if seen_statuses else extract_tool_progress_event(raw_reply)
                        if progress and progress != last_progress:
                            last_progress = progress
                            set_progress(progress)
                        elif content_added and time.time() - last_stream_tick >= 5:
                            last_stream_tick = time.time()
                            set_progress(f"Receiving model output ({len(raw_reply):,} chars); waiting for workspace tool calls...")
                    return raw_reply
                return extract_reply_from_response(response)

            set_progress("Starting model stream...")
            reply = asyncio.run(collect_reply())

            set_progress("Finalizing workspace response...")
            reply, statuses, suggested_title = finalize_agent_visible_reply(reply, user["id"], req.conversationId)
            if statuses:
                set_progress(statuses[-1])

            messages = [m.model_dump() for m in req.messages]
            messages.append({"role": "assistant", "content": reply})
            save_chat_record(
                user["id"],
                req.conversationId,
                suggested_title or chat_title_from_messages(messages),
                messages,
                updated_at=time.time(),
            )
            update_agent_job(
                job_id,
                status="completed",
                progress=statuses[-1] if statuses else "Completed.",
                reply=reply,
                completed=True,
            )
        except AgentJobCancelled:
            update_agent_job(job_id, status="cancelled", progress="Stopped by user.", error="", completed=True)
        except Exception as exc:
            update_agent_job(job_id, status="failed", progress="The agent hit an error.", error=str(exc), completed=True)

    @app.post("/chat/jobs", response_model=AgentJobStartResponse)
    @app.post("/api/chat/jobs", response_model=AgentJobStartResponse)
    def start_agent_job(req: WebChatRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        token_value = ""
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token_value = auth_header.split(" ", 1)[1]

        chat_messages = [m.model_dump() for m in req.messages]
        title = chat_title_from_messages(chat_messages)
        save_chat_record(user["id"], req.conversationId, title, redact_attachment_payloads(chat_messages), updated_at=time.time())

        latest_user = next((m["content"] for m in reversed(chat_messages) if m.get("role") == "user"), "")
        progress = "Queued: preparing workspace..."
        register_project_workspace(user["id"], req.conversationId, req.projectPath, request)
        workspace_dir = workspace_dir_for(user["id"], req.conversationId)
        copy_workspace_templates(workspace_dir)

        job_id = uuid.uuid4().hex
        now = time.time()
        conn = sqlite3.connect("users.db")
        try:
            conn.execute("""
                INSERT INTO agent_jobs (id, user_id, chat_id, status, progress, reply, error, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (job_id, user["id"], req.conversationId, "queued", progress, "", "", now, now, None))
            conn.commit()
        finally:
            conn.close()

        worker_req = req.model_copy(deep=True)
        thread = threading.Thread(target=run_agent_job, args=(job_id, user, token_value, worker_req), daemon=True)
        thread.start()
        return {
            "jobId": job_id,
            "chatId": req.conversationId,
            "status": "queued",
            "progress": progress,
            "roadmap": read_workspace_roadmap(workspace_dir),
        }

    @app.get("/chat/jobs")
    @app.get("/api/chat/jobs")
    def list_agent_jobs(request: Request, status: Optional[str] = None):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        expire_stale_agent_jobs(user["id"])
        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM agent_jobs WHERE user_id = ? AND status = ? ORDER BY updated_at DESC LIMIT 50",
                    (user["id"], status),
                )
            else:
                cursor.execute(
                    "SELECT * FROM agent_jobs WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50",
                    (user["id"],),
                )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return {"jobs": [job_row_to_dict(r) for r in rows]}

    @app.get("/chat/jobs/{job_id}")
    @app.get("/api/chat/jobs/{job_id}")
    def get_agent_job(job_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        expire_stale_agent_jobs(user["id"])
        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agent_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"]))
            row = cursor.fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Agent job not found")
        return {"job": job_row_to_dict(row)}

    @app.post("/chat/jobs/{job_id}/rollback")
    @app.post("/api/chat/jobs/{job_id}/rollback")
    def rollback_agent_job_diff(job_id: str, req: WorkspaceDiffActionRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM agent_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"])).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Agent job not found")
        workspace_dir = workspace_dir_for(row["user_id"], row["chat_id"])
        if not rollback_workspace_diff(workspace_dir, req.path):
            raise HTTPException(status_code=404, detail="Diff not found or could not be rolled back")
        return {"ok": True, "path": req.path}

    @app.post("/chat/jobs/{job_id}/approve")
    @app.post("/api/chat/jobs/{job_id}/approve")
    def approve_agent_job_diff(job_id: str, req: WorkspaceDiffActionRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM agent_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"])).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Agent job not found")
        workspace_dir = workspace_dir_for(row["user_id"], row["chat_id"])
        if not set_workspace_diff_approval(workspace_dir, req.path, True):
            raise HTTPException(status_code=404, detail="Diff not found")
        return {"ok": True, "path": req.path}

    @app.post("/chat/jobs/{job_id}/cancel")
    @app.post("/api/chat/jobs/{job_id}/cancel")
    def cancel_agent_job(job_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM agent_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"])).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Agent job not found")
        if row["status"] in {"completed", "failed", "cancelled"}:
            return {"job": job_row_to_dict(row)}

        update_agent_job(job_id, status="cancelled", progress="Stopped by user.", error="", completed=True)
        conn = sqlite3.connect("users.db")
        try:
            conn.row_factory = sqlite3.Row
            updated = conn.execute("SELECT * FROM agent_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"])).fetchone()
        finally:
            conn.close()
        return {"job": job_row_to_dict(updated)}

    @app.get("/status")
    @app.get("/api/status")
    def get_server_status():
        import platform
        load_avg = [0.0, 0.0, 0.0]
        cpu_temp = None
        try:
            if hasattr(os, "getloadavg"):
                la = os.getloadavg()
                load_avg = [round(x, 2) for x in la]
        except Exception:
            pass
        try:
            import psutil
            cpu_temp_info = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            for key in ("coretemp", "cpu_thermal", "cpu-thermal", "k10temp", "acpitz"):
                if key in cpu_temp_info and cpu_temp_info[key]:
                    cpu_temp = cpu_temp_info[key][0].current
                    break
        except Exception:
            pass
        active_jobs = 0
        try:
            expire_stale_agent_jobs()
            conn = sqlite3.connect("users.db")
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM agent_jobs WHERE status IN ('queued','running')")
                row2 = cursor.fetchone()
                active_jobs = row2["cnt"] if row2 else 0
            finally:
                conn.close()
        except Exception:
            pass
        load_1min = load_avg[0] if load_avg else 0.0
        cpu_count = 1
        try:
            import psutil
            cpu_count = psutil.cpu_count(logical=True) or 1
        except Exception:
            try:
                cpu_count = os.cpu_count() or 1
            except Exception:
                pass
        high_load = (
            load_1min > (cpu_count * 0.8) or
            active_jobs >= 2 or
            (cpu_temp is not None and cpu_temp > 80)
        )
        reason = ""
        if load_1min > (cpu_count * 0.8):
            reason = "high CPU load"
        elif active_jobs >= 2:
            reason = f"{active_jobs} jobs running"
        elif cpu_temp is not None and cpu_temp > 80:
            reason = f"CPU temp {cpu_temp:.0f}°C"
        return {
            "high_load": high_load,
            "reason": reason,
            "load_avg": load_avg,
            "active_jobs": active_jobs,
            "cpu_temp": cpu_temp,
        }

    @app.post("/api/shell/execute")
    async def remote_shell_execute(request: Request):
        """Execute shell commands remotely and return output with ANSI colors preserved."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        command = body.get("command", "").strip()
        if not command:
            raise HTTPException(status_code=400, detail="No command provided")
        
        cwd = body.get("cwd") or os.getcwd()
        cwd = os.path.expanduser(cwd)
        if not os.path.isdir(cwd):
            cwd = os.getcwd()
        
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "cwd": cwd,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": "Command timed out",
                "cwd": cwd,
            }
        except Exception as exc:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": str(exc),
                "cwd": cwd,
            }

    @app.post("/api/shell/ls")
    async def remote_shell_ls(request: Request):
        """List directory contents."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        path = body.get("path", ".") or "."
        path = os.path.expanduser(path)
        
        try:
            entries = sorted(os.listdir(path))
            detailed = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                try:
                    stat = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    size = stat.st_size if not is_dir else 0
                    detailed.append({
                        "name": entry,
                        "is_dir": is_dir,
                        "size": size,
                    })
                except OSError:
                    detailed.append({"name": entry, "is_dir": False, "size": 0})
            return {"entries": detailed, "path": os.path.abspath(path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/shell/pwd")
    async def remote_shell_pwd(request: Request):
        """Get current working directory."""
        return {"cwd": os.getcwd()}

    @app.post("/api/shell/cd")
    async def remote_shell_cd(request: Request):
        """Change directory (returns the new working directory for the session)."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        path = body.get("path", ".") or "."
        path = os.path.expanduser(path)
        
        try:
            os.chdir(path)
            return {"cwd": os.getcwd()}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot change directory: {exc}")

    @app.post("/api/shell/mkdir")
    async def remote_shell_mkdir(request: Request):
        """Create a directory."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        path = body.get("path", "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="No path provided")
        
        path = os.path.expanduser(path)
        try:
            os.makedirs(path, exist_ok=True)
            return {"created": os.path.abspath(path), "exists": os.path.isdir(path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot create directory: {exc}")

    @app.get("/api/cli/client")
    @app.get("/cli/client")
    def get_cli_remote_client():
        """Serve the thin stdlib-only CLI client for remote machines (no Geocentric install)."""
        client_path = Path(__file__).resolve().parent.parent / "scripts" / "geocentric-code-client.py"
        if not client_path.exists():
            raise HTTPException(status_code=404, detail="CLI client script not found on host.")
        return PlainTextResponse(
            client_path.read_text(encoding="utf-8"),
            media_type="text/x-python",
            headers={"Content-Disposition": "inline; filename=geocentric-code-client.py"},
        )

    @app.get("/system/telemetry")
    @app.get("/api/system/telemetry")
    def get_system_telemetry(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            cpu_percent = float(psutil.cpu_percent(interval=0.0))
        except Exception:
            cpu_percent = 0.0
        try:
            memory_percent = float(psutil.virtual_memory().percent)
        except Exception:
            memory_percent = 0.0
        try:
            disk_percent = float(psutil.disk_usage(str(Path.cwd())).percent)
        except Exception:
            disk_percent = 0.0
        return {
            "cpuPercent": cpu_percent,
            "memoryPercent": memory_percent,
            "diskPercent": disk_percent,
            "gpuPercent": None,
        }

    @app.get("/workspaces/{chat_id}/roadmap")
    @app.get("/api/workspaces/{chat_id}/roadmap")
    def get_workspace_roadmap(chat_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        workspace_dir = workspace_dir_for(user["id"], chat_id)
        return {"roadmap": read_workspace_roadmap(workspace_dir)}

    web_index = Path(__file__).parent / "web" / "index.html"
    dashboard_path = Path(__file__).parent / "web" / "dashboard.html"

    from fastapi.responses import RedirectResponse

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web_index, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

    @app.get("/community")
    def community_page():
        return RedirectResponse(url="/?msg=community_coming_soon")

    @app.get("/updates")
    def updates_page():
        return RedirectResponse(url="/?msg=updates_coming_soon")

    def get_terminal_session_or_404(session_id: str, user_id: int | str, chat_id: str) -> SandboxTerminalSession:
        cleanup_terminal_sessions()
        with TERMINAL_SESSIONS_LOCK:
            session = TERMINAL_SESSIONS.get(session_id)
        if not session or session.user_id != str(user_id) or session.chat_id != chat_id:
            raise HTTPException(status_code=404, detail="Terminal session not found")
        return session

    def resolve_terminal_target(user: Dict[str, Any], chat_id: str, filename: str) -> tuple[Path, Path]:
        clean_filename = filename.strip()
        if not clean_filename:
            raise HTTPException(status_code=400, detail="filename is required")
        if not clean_filename.endswith(".py"):
            raise HTTPException(status_code=400, detail="Only Python files can be run in the workspace terminal")

        workspace_dir = workspace_dir_for(user["id"], chat_id)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        target_path = (workspace_dir / clean_filename).resolve()
        if not path_is_inside(target_path, workspace_dir):
            raise HTTPException(status_code=403, detail="Forbidden: Escape attempt detected.")
        if not target_path.exists() or not target_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        syntax_ok, _, syntax_error = read_python_source_for_check(target_path, clean_filename)
        if not syntax_ok:
            raise HTTPException(status_code=400, detail=syntax_error)

        return workspace_dir, target_path

    @app.post("/workspaces/{chat_id}/terminal/start")
    @app.post("/api/workspaces/{chat_id}/terminal/start")
    def start_workspace_terminal(chat_id: str, req: TerminalStartRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        cleanup_terminal_sessions()
        filename = req.filename.strip()
        workspace_dir, target_path = resolve_terminal_target(user, chat_id, filename)
        session = SandboxTerminalSession(user["id"], chat_id, filename, workspace_dir, target_path)
        try:
            session.start()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to start terminal: {exc}")

        with TERMINAL_SESSIONS_LOCK:
            TERMINAL_SESSIONS[session.id] = session

        return {
            "sessionId": session.id,
            "filename": filename,
            "output": session.drain_output(),
            "running": session.is_running(),
            "returncode": session.returncode,
        }

    @app.get("/workspaces/{chat_id}/terminal/{session_id}/poll")
    @app.get("/api/workspaces/{chat_id}/terminal/{session_id}/poll")
    def poll_workspace_terminal(chat_id: str, session_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        session = get_terminal_session_or_404(session_id, user["id"], chat_id)
        return {
            "sessionId": session.id,
            "filename": session.filename,
            "output": session.drain_output(),
            "running": session.is_running(),
            "returncode": session.returncode,
        }

    @app.post("/workspaces/{chat_id}/terminal/{session_id}/input")
    @app.post("/api/workspaces/{chat_id}/terminal/{session_id}/input")
    def write_workspace_terminal(chat_id: str, session_id: str, req: TerminalInputRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        session = get_terminal_session_or_404(session_id, user["id"], chat_id)
        try:
            session.write_input(req.input)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "sessionId": session.id,
            "output": session.drain_output(),
            "running": session.is_running(),
            "returncode": session.returncode,
        }

    @app.post("/workspaces/{chat_id}/terminal/{session_id}/stop")
    @app.post("/api/workspaces/{chat_id}/terminal/{session_id}/stop")
    def stop_workspace_terminal(chat_id: str, session_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        session = get_terminal_session_or_404(session_id, user["id"], chat_id)
        session.stop()
        return {
            "sessionId": session.id,
            "output": session.drain_output(),
            "running": session.is_running(),
            "returncode": session.returncode,
        }

    class CronJobCreateRequest(BaseModel):
        name: str
        prompt: str
        interval_minutes: int
        interval_hours: int
        model: Optional[str] = "geocentric-local"

    @app.get("/api/cron-jobs")
    def get_cron_jobs(request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cron_jobs WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
        rows = cursor.fetchall()
        conn.close()
        jobs = []
        for r in rows:
            try:
                prompt_val = r["prompt"]
            except:
                try:
                    prompt_val = r["command"]
                except:
                    prompt_val = ""
            try:
                hours_val = r["interval_hours"]
                mins_val = r["interval_minutes"]
            except:
                hours_val = 0
                mins_val = 5
            try:
                model_val = r["model"]
            except:
                model_val = "geocentric-local"

            jobs.append({
                "id": r["id"],
                "name": r["name"],
                "prompt": prompt_val,
                "model": model_val or "geocentric-local",
                "interval_hours": hours_val,
                "interval_minutes": mins_val,
                "last_run": r["last_run"],
                "created_at": r["created_at"]
            })
        return {"jobs": jobs}

    @app.post("/api/cron-jobs")
    def create_cron_job(req: CronJobCreateRequest, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if req.interval_hours * 60 + req.interval_minutes < 1:
            raise HTTPException(status_code=400, detail="Minimum interval is 1 minute.")

        job_id = str(uuid.uuid4())
        model = (req.model or "geocentric-local").strip() or "geocentric-local"
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cron_jobs)")
        columns = {row[1] for row in cursor.fetchall()}
        values = {
            "id": job_id,
            "user_id": user["id"],
            "name": req.name,
            "prompt": req.prompt,
            "model": model,
            "interval_minutes": req.interval_minutes,
            "interval_hours": req.interval_hours,
            "last_run": None,
            "created_at": time.time(),
            "command": req.prompt,
            "expression": f"*/{max(1, req.interval_hours * 60 + req.interval_minutes)} * * * *",
        }
        insert_columns = [column for column in values if column in columns]
        placeholders = ", ".join("?" for _ in insert_columns)
        cursor.execute(
            f"INSERT INTO cron_jobs ({', '.join(insert_columns)}) VALUES ({placeholders})",
            [values[column] for column in insert_columns],
        )
        conn.commit()
        conn.close()
        return {"id": job_id, "name": req.name, "prompt": req.prompt, "model": model, "interval_hours": req.interval_hours, "interval_minutes": req.interval_minutes}

    @app.delete("/api/cron-jobs/{job_id}")
    def delete_cron_job(job_id: str, request: Request):
        user = get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cron_jobs WHERE id = ? AND user_id = ?", (job_id, user["id"]))
        conn.commit()
        conn.close()
        return {"success": True}

    @app.get("/api/workspaces/{chat_id}/zip")
    def download_workspace_zip(chat_id: str, request: Request):
        from fastapi import BackgroundTasks
        user = get_user_from_request(request)

        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        workspace_dir = workspace_dir_for(user["id"], chat_id)
        if not workspace_dir.exists() or not workspace_dir.is_dir():
            raise HTTPException(status_code=404, detail="Workspace directory not found")

        import tempfile
        import zipfile

        temp_dir = Path(tempfile.gettempdir())
        zip_path = temp_dir / f"workspace_{chat_id}_{uuid.uuid4().hex[:8]}.zip"

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for root_path, dirs, files in os.walk(workspace_dir):
                    for file in files:
                        file_path = Path(root_path) / file
                        rel_path = file_path.relative_to(workspace_dir)
                        zip_file.write(file_path, rel_path)

            bg_tasks = BackgroundTasks()
            def remove_file(path: Path):
                try:
                    if path.exists():
                        os.remove(path)
                except Exception as e:
                    print(f"Error removing temp zip file: {e}")

            bg_tasks.add_task(remove_file, zip_path)

            return FileResponse(zip_path, filename=f"workspace_{chat_id}.zip", media_type="application/zip", background=bg_tasks)
        except Exception as e:
            if zip_path.exists():
                try:
                    os.remove(zip_path)
                except:
                    pass
            raise HTTPException(status_code=500, detail=f"Failed to create ZIP: {str(e)}")

    @app.get("/api/download/{chat_id}/{filename:path}")
    @app.get("/download/{chat_id}/{filename:path}")
    @app.get("/api/workspaces/{chat_id}/{filename:path}")
    def download_workspace_file(chat_id: str, filename: str, request: Request):
        user = get_user_from_request(request)

        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        workspace_dir = workspace_dir_for(user["id"], chat_id)
        target_path = (workspace_dir / filename).resolve()
        if not path_is_inside(target_path, workspace_dir):
            raise HTTPException(status_code=403, detail="Forbidden: Escape attempt detected.")

        if not target_path.exists() or not target_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(target_path)

    @app.get("/manifest.json")
    def get_manifest() -> JSONResponse:
        content = {
            "name": "Geocentric AI Companion",
            "short_name": "Geocentric",
            "description": "Cloud-trained AI, running securely in the cloud.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#111111",
            "theme_color": "#6c8ef5",
            "orientation": "portrait",
            "icons": [
                {
                    "src": "https://cdn.jsdelivr.net/gh/tabler/tabler-icons@v2.44.0/icons/png/planet.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable"
                }
            ]
        }
        return JSONResponse(content=content, media_type="application/manifest+json")

    @app.get("/api/device-context")
    def get_device_context(request: Request) -> Dict[str, Any]:
        import platform
        import socket
        import psutil

        client_ip = request.client.host if request.client else "127.0.0.1"

        # Determine all local server IPs
        local_ips = ["127.0.0.1", "localhost"]
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None):
                ip = info[4][0]
                if ip not in local_ips:
                    local_ips.append(ip)
        except Exception:
            pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            if lan_ip not in local_ips:
                local_ips.append(lan_ip)
            s.close()
        except Exception:
            pass

        is_local = (client_ip in local_ips) or (client_ip == "testclient")

        # Get system statistics
        try:
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
        except Exception:
            cpu_percent = 0.0
            memory_percent = 0.0

        return {
            "client_ip": client_ip,
            "is_local_device": is_local,
            "local_ips": [ip for ip in local_ips if ":" not in ip], # Filter IPv6 for simplicity
            "system": {
                "device": str(device),
                "dtype": str(dtype),
                "platform": platform.system(),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
            }
        }

    @app.get("/training-dashboard")
    def dashboard_index() -> FileResponse:
        return FileResponse(dashboard_path)

    @app.get("/training-dashboard/metrics")
    def training_metrics() -> JSONResponse:
        try:
            data = load_training_metrics(model_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Training metrics not found")
        return JSONResponse(content=data)

    @app.get("/training-dashboard/system")
    def training_system() -> JSONResponse:
        # Return CPU, memory and GPU utilization (if available)
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu = 0.0
            mem = 0.0
        gpu = None
        try:
            out = subprocess.check_output([
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ], stderr=subprocess.DEVNULL)
            line = out.decode().strip().split("\n")[0]
            util, used, total = [float(x.strip()) for x in line.split(",")]
            gpu = {"util_percent": util, "memory_used": used, "memory_total": total}
        except Exception:
            gpu = None
        return JSONResponse(content={"cpu_percent": cpu, "memory_percent": mem, "gpu": gpu})

    # Command center endpoints
    @app.post("/command-center/start")
    async def cc_start(req: Request) -> JSONResponse:
        body = await req.json()
        cmd = body.get("cmd")
        cwd = body.get("cwd")
        if not cmd:
            raise HTTPException(status_code=400, detail="cmd is required")
        rec = command_center.start_command(cmd, cwd=cwd)
        return JSONResponse(content={"id": rec.id, "pid": rec.pid, "status": rec.status})

    @app.post("/command-center/stop")
    async def cc_stop(req: Request) -> JSONResponse:
        body = await req.json()
        rid = body.get("id")
        if not rid:
            raise HTTPException(status_code=400, detail="id is required")
        try:
            rec = command_center.stop_command(rid)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown id")
        return JSONResponse(content={"id": rec.id, "status": rec.status})

    @app.post("/command-center/pause")
    async def cc_pause(req: Request) -> JSONResponse:
        body = await req.json()
        rid = body.get("id")
        if not rid:
            raise HTTPException(status_code=400, detail="id is required")
        try:
            rec = command_center.pause_command(rid)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown id")
        return JSONResponse(content={"id": rec.id, "status": rec.status})

    @app.post("/command-center/resume")
    async def cc_resume(req: Request) -> JSONResponse:
        body = await req.json()
        rid = body.get("id")
        if not rid:
            raise HTTPException(status_code=400, detail="id is required")
        try:
            rec = command_center.resume_command(rid)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown id")
        return JSONResponse(content={"id": rec.id, "status": rec.status})

    @app.get("/command-center/list")
    def cc_list() -> JSONResponse:
        return JSONResponse(content=command_center.list_commands())

    @app.get("/v1/models")
    @app.get("/api/v1/models")
    def models() -> Dict[str, Any]:
        default_models = []
        seen = set()

        # Check if local model_dir exists
        p_dir = Path(model_dir)
        if p_dir.exists() and p_dir.is_dir():
            default_models = [
                {"id": "geocentric-local", "object": "model", "owned_by": "local"},
                {"id": "geocentric-local-thinking", "object": "model", "owned_by": "local"},
                {"id": "geocentric-raw", "object": "model", "owned_by": "local"},
            ]
            seen = {"geocentric-local", "geocentric-local-thinking", "geocentric-raw"}

        # Dynamically list models in models/ and runs/
        for folder in ["models", "runs"]:
            p = Path(folder)
            if p.exists() and p.is_dir():
                for path in p.rglob("*"):
                    if path.is_dir():
                        # Check if it has configs or checkpoint files
                        if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                            rel_name = str(path.relative_to(p))
                            if rel_name not in seen:
                                default_models.append({"id": rel_name, "object": "model", "owned_by": "local"})
                                seen.add(rel_name)

        # Dynamically append available Ollama models if running locally
        try:
            ollama_models = get_ollama_models()
            for m in ollama_models:
                if m not in seen:
                    default_models.append({"id": m, "object": "model", "owned_by": "ollama"})
                    seen.add(m)
        except Exception:
            pass

        return {
            "object": "list",
            "data": default_models,
        }

    @app.post("/v1/chat/completions")
    @app.post("/api/v1/chat/completions")
    async def chat(req: ChatRequest):
        if cli_model and is_generic_model_name(req.model):
            req.model = cli_model

        if not req.messages:
            raise HTTPException(status_code=400, detail="messages cannot be empty")

        clean_model = req.model.replace("-thinking", "").replace("thinking", "").strip()

        # Check available local models
        local_model_names = set()
        p_dir = Path(model_dir)
        if p_dir.exists() and p_dir.is_dir():
            local_model_names.update({"geocentric-local", "geocentric-raw", "geocentric-local-thinking"})
        for folder in ["models", "runs"]:
            p = Path(folder)
            if p.exists() and p.is_dir():
                for path in p.rglob("*"):
                    if path.is_dir():
                        if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                            local_model_names.add(str(path.relative_to(p)))

        # Fetch Ollama models
        ollama_models = []
        try:
            ollama_models = get_ollama_models()
        except Exception:
            pass

        # Determine Ollama vs Local
        is_ollama_model = False
        matched_ollama_model = clean_model

        if clean_model not in local_model_names:
            is_ollama_model = True
            is_instant = not ("thinking" in req.model.lower() or "deepseek" in req.model.lower() or "r1" in req.model.lower())
            matched_ollama_model = get_ollama_model_for_mode(is_instant, clean_model)

        matched_model = matched_ollama_model

        import asyncio

        if is_ollama_model:
            print(f"Proxying request to local Ollama service for model: {matched_model}")
            base_url = "http://127.0.0.1:11434/v1/chat/completions"
            payload = req.model_dump()
            payload["model"] = matched_model

            if req.stream:
                async def event_stream_ollama():
                    req_http = urllib.request.Request(
                        base_url,
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"}
                    )
                    try:
                        # Perform blocking network calls on the main thread but yield frequently
                        response = await asyncio.to_thread(urllib.request.urlopen, req_http)
                        while True:
                            line = await asyncio.to_thread(response.readline)
                            if not line:
                                break
                            if line:
                                    decoded_line = line.decode()
                                    if decoded_line.startswith("data:"):
                                        data_str = decoded_line.replace("data:", "").strip()
                                        if data_str != "[DONE]":
                                            try:
                                                chunk = json.loads(data_str)
                                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                                content = delta.get("content", "")
                                                reasoning_content = delta.get("reasoning_content", "")
                                                if reasoning_content:
                                                    _server_stream_write(reasoning_content)
                                                if content:
                                                    _server_stream_write(content)
                                            except Exception:
                                                pass
                                    yield decoded_line
                                    await asyncio.sleep(0.001)
                    except Exception as exc:
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': f'Error proxying to Ollama: {str(exc)}'}}]})}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(event_stream_ollama(), media_type="text/event-stream")
            else:
                try:
                    req_http = urllib.request.Request(
                        base_url,
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"}
                    )
                    def fetch_resp():
                        with urllib.request.urlopen(req_http) as response:
                            return json.loads(response.read().decode())
                    res_json = await asyncio.to_thread(fetch_resp)
                    return res_json
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"Ollama proxy error: {str(exc)}")

        # Load the model on-demand
        model, tokenizer = get_model_and_tokenizer(req.model)

        messages = [m.model_dump() for m in req.messages]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")

        is_raw_mode = "raw" in req.model.lower() or "autocomplete" in req.model.lower()
        if is_raw_mode:
            # Under raw causal generation mode, pass the exact text typed by the user
            # without wrapping it in SFT templates, so it operates as a raw text autocomplete guesser
            prompt = messages[-1]["content"]
        else:
            # Check if it is a Gemma model to use a custom, token-perfect robust template
            is_gemma = False
            try:
                if req.model in {"geocentric-local", "geocentric-local-thinking", "geocentric-raw", "geocentric", "geocentric2_1"}:
                    target_path = Path(model_dir)
                else:
                    path_opt = Path(req.model)
                    if path_opt.exists():
                        target_path = path_opt
                    else:
                        candidates = [Path("models") / req.model, Path("runs") / req.model, Path(req.model)]
                        target_path = Path(model_dir)
                        for c in candidates:
                            if c.exists():
                                target_path = c
                                break
                if "gemma" in str(target_path).lower() or "gemma" in req.model.lower():
                    is_gemma = True
            except Exception:
                pass

            if is_gemma:
                prompt = ""
                if system:
                    prompt += f"<start_of_turn>system\n{system}<end_of_turn>\n"
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "").strip()
                    if not content or role == "system":
                        continue
                    if role == "user":
                        prompt += f"<start_of_turn>user\n{content}<end_of_turn>\n"
                    elif role == "assistant":
                        prompt += f"<start_of_turn>model\n{content}<end_of_turn>\n"
                prompt += "<start_of_turn>model\n"
            elif hasattr(tokenizer, "apply_chat_template"):
                try:
                    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                except Exception as exc:
                    print(f"⚠️ apply_chat_template failed: {exc}")
                    prompt = build_chat_prompt(messages, system=system)
            else:
                prompt = build_chat_prompt(messages, system=system)

        print(f"--- SERVER BUILT PROMPT ---\n{prompt}\n---------------------------")

        if req.stream:
            async def event_stream():
                any_token = False
                q = run_generator_in_thread(
                    stream_text,
                    model=model,
                    tokenizer=tokenizer,
                    prompt=prompt,
                    device=device,
                    max_new_tokens=req.max_tokens,
                    temperature=req.temperature,
                    top_k=req.top_k,
                    repetition_penalty=req.repetition_penalty,
                )
                async for token in async_generator_from_queue(q):
                    any_token = True
                    _server_stream_write(token)
                    yield sse_chunk(token)
                    await asyncio.sleep(0.005) # Crucial: yields back to event loop to prevent UI/cursor freezing
                if not any_token:
                    yield sse_chunk("I trained in the cloud, but I need more data or training steps to answer well yet.")
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        text = await asyncio.to_thread(
            generate_text,
            model=model,
            tokenizer=tokenizer,
            prompt=prompt,
            device=device,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_k=req.top_k,
            repetition_penalty=req.repetition_penalty,
        )
        return {"choices": [{"message": {"role": "assistant", "content": text}}]}

    def run_cron_scheduler():
        print("⏳ Cron Prompt Scheduler started.")
        while True:
            try:
                time.sleep(10)
                now = time.time()
                conn = sqlite3.connect("users.db")
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM cron_jobs")
                jobs = cursor.fetchall()

                for job in jobs:
                    interval_seconds = (job["interval_hours"] * 60 + job["interval_minutes"]) * 60
                    if interval_seconds < 60:
                        interval_seconds = 60

                    last_run = job["last_run"]
                    should_run = False
                    if last_run is None:
                        should_run = True
                    elif now - last_run >= interval_seconds:
                        should_run = True

                    if should_run:
                        prompt = (job["prompt"] or "").strip()
                        if not prompt:
                            try:
                                prompt = (job["command"] or "").strip()
                            except Exception:
                                prompt = ""
                        model = (job["model"] or "geocentric-local").strip()
                        if not prompt:
                            print(f"Skipping cron job '{job['name']}' because it has no prompt.")
                            cursor.execute("UPDATE cron_jobs SET last_run = ? WHERE id = ?", (now, job["id"]))
                            conn.commit()
                            continue
                        print(f"⏰ Cron job '{job['name']}' triggered! Model: '{model}' Prompt: '{prompt}'")
                        cursor.execute("UPDATE cron_jobs SET last_run = ? WHERE id = ?", (now, job["id"]))
                        conn.commit()

                        try:
                            cursor.execute("SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1", (job["user_id"],))
                            chat_row = cursor.fetchone()

                            if chat_row:
                                chat_id = chat_row["id"]
                                messages = json.loads(chat_row["messages"])
                            else:
                                chat_id = str(uuid.uuid4())
                                messages = []

                            messages.append({"role": "user", "content": prompt})
                            cursor.execute("INSERT OR REPLACE INTO chats (id, user_id, title, messages, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                                            (chat_id, job["user_id"], prompt[:50], json.dumps(messages), time.time(), time.time()))

                            agent_job_id = uuid.uuid4().hex
                            cursor.execute("""
                                INSERT INTO agent_jobs (id, user_id, chat_id, status, progress, reply, error, created_at, updated_at, completed_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (agent_job_id, job["user_id"], chat_id, "queued", f"Cron execution: {prompt[:50]}", "", "", now, now, None))
                            conn.commit()

                            user_dict = {"id": job["user_id"], "name": "Workspace", "email": ""}
                            chat_msg_objs = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
                            req_obj = WebChatRequest(
                                model=model,
                                conversationId=chat_id,
                                messages=chat_msg_objs,
                                stream=True,
                                agentMode=True,
                                modelMode="thinking",
                            )

                            threading.Thread(target=run_agent_job, args=(agent_job_id, user_dict, "", req_obj), daemon=True).start()
                        except Exception as start_err:
                            print(f"Error starting agent job from cron: {start_err}")

                conn.close()
            except Exception as e:
                print(f"Error in cron scheduler loop: {e}")
                time.sleep(5)

    threading.Thread(target=run_cron_scheduler, daemon=True).start()

    security_basic = HTTPBasic()

    def verify_admin(credentials: HTTPBasicCredentials = Depends(security_basic)):
        admin_user, admin_pass = get_admin_credentials()
        if credentials.username != admin_user or credentials.password != admin_pass:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect admin credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    @app.get("/admin/controlpanel")
    def admin_controlpanel_endpoint(admin: str = Depends(verify_admin)):
        admin_html_path = Path(__file__).parent / "web" / "admin.html"
        return FileResponse(admin_html_path)

    @app.get("/admin/api/config")
    def admin_get_config(admin: str = Depends(verify_admin)):
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()

        cursor.execute("SELECT value FROM system_config WHERE key = 'downgrade_model'")
        row = cursor.fetchone()
        downgrade_model = row[0] if row else "geocentric-local"

        cursor.execute("SELECT value FROM system_config WHERE key = 'high_load_threshold'")
        row = cursor.fetchone()
        high_load_threshold = row[0] if row else "10"
        conn.close()

        local_models = ["geocentric-local", "geocentric-raw", "geocentric-local-thinking"]
        ollama_models = get_ollama_models()
        system_load = get_current_system_load()

        return {
            "downgrade_model": downgrade_model,
            "high_load_threshold": high_load_threshold,
            "available_models": list(set(local_models + ollama_models)),
            "chats_count": 0,
            "agents_count": 0,
            "system_load": system_load,
        }

    @app.post("/admin/api/config")
    async def admin_set_config(req_data: dict, admin: str = Depends(verify_admin)):
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")

        if "downgrade_model" in req_data:
            cursor.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES ('downgrade_model', ?)",
                (str(req_data["downgrade_model"]),),
            )
        if "high_load_threshold" in req_data:
            cursor.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES ('high_load_threshold', ?)",
                (str(req_data["high_load_threshold"]),),
            )

        conn.commit()
        conn.close()
        return {"status": "success"}

    @app.get("/admin/api/users")
    def admin_list_users(admin: str = Depends(verify_admin)):
        conn = sqlite3.connect("users.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, email, is_pro, infinite_usage, token_limit, tokens_used, image_limit, images_used, limited_until FROM users"
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @app.post("/admin/api/users/{user_id}/update")
    async def admin_update_user(user_id: str, req_data: dict, admin: str = Depends(verify_admin)):
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        is_pro = req_data.get("is_pro", 0)
        infinite_usage = req_data.get("infinite_usage", 0)
        token_limit = req_data.get("token_limit", DEFAULT_FREE_TOKEN_LIMIT)
        image_limit = req_data.get("image_limit", DEFAULT_FREE_IMAGE_LIMIT)

        cursor.execute(
            """
            UPDATE users
            SET is_pro = ?, infinite_usage = ?, token_limit = ?, image_limit = ?
            WHERE id = ?
            """,
            (is_pro, infinite_usage, token_limit, image_limit, user_id),
        )

        conn.commit()
        conn.close()
        return {"status": "success"}

    @app.post("/admin/api/users/{user_id}/reset")
    def admin_reset_user(user_id: str, admin: str = Depends(verify_admin)):
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users
            SET tokens_used = 0, images_used = 0, limited_until = 0.0
            WHERE id = ?
            """,
            (user_id,),
        )
        conn.commit()
        conn.close()
        return {"status": "success"}

    @app.post("/admin/api/users/{user_id}/add_usage")
    async def admin_add_user_usage(user_id: str, req_data: dict, admin: str = Depends(verify_admin)):
        add_tokens = int(req_data.get("add_tokens", 0))
        add_images = int(req_data.get("add_images", 0))
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT token_limit, image_limit FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            new_token_limit = max(0, row[0] + add_tokens)
            new_image_limit = max(0, row[1] + add_images)
            cursor.execute(
                """
                UPDATE users
                SET token_limit = ?, image_limit = ?
                WHERE id = ?
                """,
                (new_token_limit, new_image_limit, user_id),
            )
        conn.commit()
        conn.close()
        return {"status": "success"}

    @app.get("/api/usage")
    def get_api_usage(request: Request):
        user = get_user_from_request(request)
        if not user:
            if request_is_local(request):
                return {
                    "is_pro": False,
                    "infinite_usage": True,
                    "token_limit": DEFAULT_FREE_TOKEN_LIMIT,
                    "tokens_used": 0,
                    "image_limit": DEFAULT_FREE_IMAGE_LIMIT,
                    "images_used": 0,
                    "limited_until": 0,
                    "reset_in_seconds": 0,
                    "system_load": get_current_system_load(),
                    "high_load_threshold": 10,
                    "is_high_load": False,
                }
            raise HTTPException(status_code=401, detail="Unauthorized")

        limits = check_user_limits(str(user["id"]))
        try:
            high_load_thresh = int(get_system_config("high_load_threshold", "10"))
        except Exception:
            high_load_thresh = 10

        reset_in = 0
        if limits["limited_until"] > 0.0 and limits["limited_until"] > time.time():
            reset_in = int(limits["limited_until"] - time.time())

        current_load = get_current_system_load()
        return {
            "is_pro": limits["is_pro"],
            "infinite_usage": limits["infinite_usage"],
            "token_limit": limits["token_limit"],
            "tokens_used": limits["tokens_used"],
            "image_limit": limits["image_limit"],
            "images_used": limits["images_used"],
            "limited_until": limits["limited_until"],
            "reset_in_seconds": reset_in,
            "system_load": current_load,
            "high_load_threshold": high_load_thresh,
            "is_high_load": current_load >= high_load_thresh,
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", default="runs/geocentric2_1")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dtype", default="auto", choices=["auto", "fp16", "float16", "fp32", "float32"])
    parser.add_argument("--modelver", default="Geocentric 2.1", help="Model version name to load")
    args = parser.parse_args()

    import uvicorn
    import socket

    app = create_app(args.model_dir, dtype_name=args.dtype, modelver=args.modelver)

    # Resolve local LAN IP address
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print("=" * 80)
    print("  GEOCENTRIC 2.1 WEB SERVER OPERATIONAL")
    print("=" * 80)
    print(f"  - Local host access:   http://localhost:{args.port}")
    print(f"  - Network device access: http://{lan_ip}:{args.port}")
    print("=" * 80)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
