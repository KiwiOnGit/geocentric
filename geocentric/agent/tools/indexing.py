"""Project-wide indexing and symbol lookup.

`grep` (search.py) is a single-pattern text search with no memory between
calls -- fine for "find this exact string" but useless for "what functions
does this codebase have" or "where is Foo defined" without brute-forcing
every file. This module is the next tier: it builds and caches a lightweight
index of the workspace (file paths/sizes and, for recognized source
languages, top-level symbol names) so the agent can jump straight to a
definition or get an overview of a large codebase instead of reading files
one at a time to build a mental map.

This is the real implementation of what the OLD codebase (geocentric/
server.py) only ever *advertised*: its system prompt told the model it had
`<project_index>`, `<semantic_search>`, and `<embedding_index>` tags, but no
handler for any of them existed in process_sandbox_tags -- they silently
no-op'd. To avoid repeating that mistake, precision is called out honestly
per tool below and in each ToolSpec description (which is what actually
reaches the model's system prompt via SystemPromptBuilder / to_prompt_catalog):

- Python symbol extraction uses the stdlib `ast` module: exact, not a
  heuristic. If `ast` can't see it (e.g. dynamically-defined functions),
  it isn't indexed.
- JS/TS/Go/Rust/Java/C-family/Ruby/PHP symbol extraction is regex-based,
  line-by-line, best-effort: it will miss unusual formatting and can
  misfire on names that merely look like a definition (inside a string or
  comment). It is a coarse navigation aid, not a language server.
- `semantic_search` is the stretch-goal tool: stdlib-only TF-IDF
  (term-frequency / inverse-document-frequency) keyword ranking over
  indexed files. It is NOT embeddings and NOT a neural model -- no
  sentence-transformers/torch model is loaded for it, specifically so it
  stays fast and dependency-free. It is genuinely useful as "fuzzy
  multi-keyword grep across the whole project" but, unlike a real
  embedding model, it cannot match synonyms or conceptual similarity
  outside the literal vocabulary used in the query and the code.
"""

from __future__ import annotations

import ast
import json
import math
import re
import time
from pathlib import Path
from typing import Any

from . import ToolContext, ToolSpec
from ..workspace import resolve_in_workspace

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".DS_Store", ".geocentric"}
_INDEX_CACHE_RELPATH = Path(".geocentric") / "index.json"
_INDEX_VERSION = 2
_MAX_FILE_BYTES_FOR_SYMBOLS = 1_500_000  # skip symbol parsing (not listing) for very large files
_MAX_INDEXED_FILES = 20_000  # safety cap so a pathological workspace can't hang the walk
_MAX_RESULTS = 50

_PY_EXTS = {".py"}
_JS_EXTS = {".js", ".jsx", ".mjs", ".cjs"}
_TS_EXTS = {".ts", ".tsx"}

# Extensions with a regex-based (heuristic) symbol extractor, mapped to a
# language label. JS/TS get their own patterns; everything else here shares
# the generic pattern table in _LANGUAGE_PATTERNS below.
_REGEX_LANG_BY_EXT = {
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
}

_KEYWORD_DENYLIST = {
    "if", "for", "while", "switch", "catch", "return", "else", "do", "try",
    "new", "delete", "sizeof", "using", "namespace", "case", "default",
    "foreach", "function", "def", "class",
}

_JS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\("), "function"),
    (re.compile(r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[\w<>\[\].,\s|]+)?\s*=>"), "function"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*function"), "function"),
    (re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"), "interface"),
    (re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*="), "type"),
]

_LANGUAGE_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "go": [
        (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "function"),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct\b"), "struct"),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+interface\b"), "interface"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), "function"),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)"), "struct"),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)"), "enum"),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)"), "trait"),
    ],
    "java": [
        (re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*interface\s+([A-Za-z_]\w*)"), "interface"),
    ],
    "csharp": [
        (re.compile(r"^\s*(?:public|private|protected|internal|static|sealed|abstract|partial|\s)*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|internal|static|\s)*interface\s+([A-Za-z_]\w*)"), "interface"),
    ],
    "c": [
        (re.compile(r"^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;{)]*\)\s*\{"), "function"),
        (re.compile(r"^\s*struct\s+([A-Za-z_]\w*)"), "struct"),
    ],
    "cpp": [
        (re.compile(r"^[A-Za-z_][\w\s\*&:<>]*?\b([A-Za-z_]\w*)\s*\([^;{)]*\)\s*\{"), "function"),
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*struct\s+([A-Za-z_]\w*)"), "struct"),
    ],
    "ruby": [
        (re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)"), "method"),
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*module\s+([A-Za-z_]\w*)"), "module"),
    ],
    "php": [
        (re.compile(r"^\s*(?:public|private|protected|static|abstract|final|\s)*function\s+([A-Za-z_]\w*)"), "function"),
        (re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)"), "class"),
    ],
}


def _detect_language(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _PY_EXTS:
        return "python"
    if ext in _JS_EXTS:
        return "javascript"
    if ext in _TS_EXTS:
        return "typescript"
    return _REGEX_LANG_BY_EXT.get(ext, "")


def _extract_python_symbols(text: str) -> list[dict[str, Any]]:
    """Exact extraction via stdlib `ast`: top-level functions/classes, plus
    one level of class methods (qualified as "Class.method"). Deliberately
    does not descend into function bodies or conditional blocks -- this is
    a lightweight index of the public shape of a file, not a full symbol
    table."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []

    symbols: list[dict[str, Any]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                kind = "method" if prefix else "function"
                symbols.append({"name": name, "kind": kind, "line": child.lineno})
            elif isinstance(child, ast.ClassDef):
                name = f"{prefix}{child.name}"
                symbols.append({"name": name, "kind": "class", "line": child.lineno})
                visit(child, prefix=f"{name}.")

    visit(tree, prefix="")
    return symbols


def _regex_extract(text: str, patterns: list[tuple[re.Pattern, str]]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, kind in patterns:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            if name in _KEYWORD_DENYLIST:
                continue
            symbols.append({"name": name, "kind": kind, "line": lineno})
            break  # one symbol per line is enough; avoids duplicate hits from overlapping patterns
    return symbols


def _extract_symbols(language: str, text: str) -> list[dict[str, Any]]:
    if language == "python":
        return _extract_python_symbols(text)
    if language in ("javascript", "typescript"):
        return _regex_extract(text, _JS_PATTERNS)
    patterns = _LANGUAGE_PATTERNS.get(language)
    if patterns:
        return _regex_extract(text, patterns)
    return []


def _cache_path(workspace_dir: Path) -> Path:
    return workspace_dir / _INDEX_CACHE_RELPATH


def _load_cache(workspace_dir: Path) -> dict[str, Any] | None:
    path = _cache_path(workspace_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != _INDEX_VERSION:
        return None
    return data


def _save_cache(workspace_dir: Path, data: dict[str, Any]) -> None:
    path = _cache_path(workspace_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # the cache is a best-effort speedup; never fail the tool call over it


def _iter_workspace_files(workspace_dir: Path):
    count = 0
    for path in workspace_dir.rglob("*"):
        if count >= _MAX_INDEXED_FILES:
            return
        if path.is_dir():
            continue
        try:
            rel_parts = path.relative_to(workspace_dir).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        count += 1
        yield path


def build_or_refresh_index(workspace_dir: Path, *, force: bool = False) -> tuple[dict[str, Any], int, int]:
    """Build the index, reusing cached per-file entries whose (size, mtime)
    haven't changed since the last build. Returns (index, rescanned_count,
    total_file_count).

    This walks (stats) every file in the workspace on every call -- that
    part is unavoidable to detect additions/deletions/changes cheaply -- but
    the expensive part, actually reading + parsing a file for symbols, is
    skipped whenever the cached (size, mtime) still matches disk. Repeated
    calls in an unchanged workspace do zero re-parsing.
    """
    cached = None if force else _load_cache(workspace_dir)
    cached_files: dict[str, Any] = cached.get("files", {}) if cached else {}

    files: dict[str, Any] = {}
    rescanned = 0
    total = 0

    for path in _iter_workspace_files(workspace_dir):
        total += 1
        rel = str(path.relative_to(workspace_dir))
        try:
            st = path.stat()
        except OSError:
            continue

        prev = cached_files.get(rel)
        if prev is not None and prev.get("mtime") == st.st_mtime and prev.get("size") == st.st_size:
            files[rel] = prev
            continue

        rescanned += 1
        language = _detect_language(path)
        symbols: list[dict[str, Any]] = []
        if language and st.st_size <= _MAX_FILE_BYTES_FOR_SYMBOLS:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                symbols = _extract_symbols(language, text)
            except OSError:
                symbols = []
        files[rel] = {"size": st.st_size, "mtime": st.st_mtime, "language": language, "symbols": symbols}

    index = {"version": _INDEX_VERSION, "generated_at": time.time(), "files": files}
    _save_cache(workspace_dir, index)
    return index, rescanned, total


def _status(ctx: ToolContext, message: str) -> None:
    if ctx.on_status:
        ctx.on_status(message)


def project_index(args: dict[str, Any], ctx: ToolContext) -> str:
    refresh = bool(args.get("refresh", False))
    _status(ctx, "Rebuilding project index" if refresh else "Loading project index")
    index, rescanned, total = build_or_refresh_index(ctx.workspace_dir, force=refresh)
    files = index["files"]

    groups: dict[str, dict[str, int]] = {}
    lang_counts: dict[str, int] = {}
    total_symbols = 0
    for rel, entry in files.items():
        parts = Path(rel).parts
        group = parts[0] + "/" if len(parts) > 1 else "(root)"
        bucket = groups.setdefault(group, {"files": 0, "symbols": 0})
        bucket["files"] += 1
        bucket["symbols"] += len(entry["symbols"])
        total_symbols += len(entry["symbols"])
        lang_counts[entry["language"] or "unrecognized"] = lang_counts.get(entry["language"] or "unrecognized", 0) + 1

    ordered = sorted(groups.items(), key=lambda kv: (-kv[1]["files"], kv[0]))
    max_groups = 40
    lines = [f"- {name} ({info['files']} files, {info['symbols']} symbols)" for name, info in ordered[:max_groups]]
    if len(ordered) > max_groups:
        lines.append(f"... {len(ordered) - max_groups} more directories")

    lang_summary = ", ".join(f"{lang}: {count}" for lang, count in sorted(lang_counts.items(), key=lambda kv: -kv[1]))

    header = (
        f"[PROJECT_INDEX RESULT] {total} files indexed "
        f"({rescanned} scanned this call, {total - rescanned} reused from cache); "
        f"{total_symbols} symbols across recognized source files."
    )
    lang_line = f"Languages (by file count): {lang_summary or 'none detected'}"
    body = "By directory:\n" + ("\n".join(lines) if lines else "(empty workspace)")
    footer = (
        "Use find_symbol(name) to jump to a definition, outline_file(path) to preview one file's symbols, "
        "or semantic_search(query) for keyword-relevance ranking across files."
    )
    return f"{header}\n{lang_line}\n{body}\n{footer}"


def find_symbol(args: dict[str, Any], ctx: ToolContext) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        return "[FIND_SYMBOL ERROR] No symbol name provided."
    _status(ctx, f"Looking up symbol: {name}")
    index, _, _ = build_or_refresh_index(ctx.workspace_dir)

    exact: list[str] = []
    fuzzy: list[str] = []
    needle = name.lower()
    for rel, entry in index["files"].items():
        for sym in entry["symbols"]:
            sym_name = sym["name"]
            leaf = sym_name.rsplit(".", 1)[-1]
            if sym_name == name or leaf == name:
                exact.append(f"{rel}:{sym['line']}: {sym['kind']} {sym_name}")
            elif needle in sym_name.lower():
                fuzzy.append(f"{rel}:{sym['line']}: {sym['kind']} {sym_name}")

    if exact:
        listing = "\n".join(sorted(exact)[:_MAX_RESULTS])
        return f"[FIND_SYMBOL RESULT] Definition(s) of '{name}':\n{listing}"
    if fuzzy:
        listing = "\n".join(sorted(fuzzy)[:_MAX_RESULTS])
        return f"[FIND_SYMBOL RESULT] No exact definition of '{name}'; closest name matches in the index:\n{listing}"
    return (
        f"[FIND_SYMBOL RESULT] No symbol named '{name}' found in the indexed source files. "
        "It may be defined in a language/file the indexer doesn't parse, dynamically generated, "
        "or the index may be stale -- try project_index(refresh=true) or grep for a broader text search."
    )


def outline_file(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args.get("path", "")).strip()
    if not rel:
        return "[OUTLINE_FILE ERROR] No path provided."
    _status(ctx, f"Outlining: {rel}")
    target = resolve_in_workspace(ctx.workspace_dir, rel)
    if not target.exists() or not target.is_file():
        return f"[OUTLINE_FILE ERROR] File '{rel}' does not exist."

    index, _, _ = build_or_refresh_index(ctx.workspace_dir)
    key = str(target.relative_to(ctx.workspace_dir))
    entry = index["files"].get(key)
    if entry is None:
        return f"[OUTLINE_FILE RESULT] '{rel}' was not found in the index (it may be inside a skipped directory)."
    if not entry["symbols"]:
        language = entry["language"] or "unrecognized file type"
        return f"[OUTLINE_FILE RESULT] '{rel}' ({language}): no symbols found."
    lines = [f"{sym['line']}: {sym['kind']} {sym['name']}" for sym in entry["symbols"]]
    return f"[OUTLINE_FILE RESULT] {rel} ({entry['language']}):\n" + "\n".join(lines)


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_SEMANTIC_MAX_FILES = 3000
_SEMANTIC_MAX_FILE_BYTES = 300_000
_SEMANTIC_TEXT_EXTS = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".rb", ".php", ".md", ".rst",
    ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".html", ".css",
    ".sh", ".bash",
}


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _tf_idf_rank(workspace_dir: Path, index: dict[str, Any], query: str, top_k: int) -> list[tuple[str, float]]:
    """Cheap, stdlib-only relevance ranking: classic TF-IDF over the query's
    own terms (not a full-corpus vocabulary/vector index -- this keeps the
    per-call cost proportional to the query, not the repo size). This is
    keyword-frequency statistics, not learned semantics; see module
    docstring and the semantic_search ToolSpec description for the
    precision caveat that must reach the model."""
    query_terms = set(_tokenize(query))
    if not query_terms:
        return []

    doc_term_freqs: dict[str, dict[str, Any]] = {}
    doc_freq: dict[str, int] = {t: 0 for t in query_terms}
    considered = 0

    for rel, entry in index["files"].items():
        if considered >= _SEMANTIC_MAX_FILES:
            break
        if Path(rel).suffix.lower() not in _SEMANTIC_TEXT_EXTS:
            continue
        if entry.get("size", 0) > _SEMANTIC_MAX_FILE_BYTES:
            continue
        try:
            text = (workspace_dir / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        considered += 1
        tokens = _tokenize(text)
        if not tokens:
            continue
        freqs: dict[str, int] = {}
        for tok in tokens:
            if tok in query_terms:
                freqs[tok] = freqs.get(tok, 0) + 1
        if freqs:
            doc_term_freqs[rel] = {"freqs": freqs, "length": len(tokens)}
            for term in freqs:
                doc_freq[term] += 1

    if not doc_term_freqs:
        return []

    num_docs = max(considered, 1)
    idf = {term: math.log((num_docs + 1) / (df + 1)) + 1.0 for term, df in doc_freq.items()}

    scores: dict[str, float] = {}
    for rel, data in doc_term_freqs.items():
        length = data["length"] or 1
        scores[rel] = sum((freq / length) * idf.get(term, 0.0) for term, freq in data["freqs"].items())

    return sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]


def semantic_search(args: dict[str, Any], ctx: ToolContext) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "[SEMANTIC_SEARCH ERROR] No query provided."
    top_k = int(args.get("max_results", 10))
    _status(ctx, f"Ranking files by keyword relevance to: {query}")
    index, _, _ = build_or_refresh_index(ctx.workspace_dir)
    ranked = _tf_idf_rank(ctx.workspace_dir, index, query, top_k)

    if not ranked:
        return (
            f"[SEMANTIC_SEARCH RESULT] No files scored for '{query}'. Reminder: this is TF-IDF keyword "
            "ranking, not neural/embedding semantic search, so it only matches literal query words -- "
            "try grep, different keywords, or find_symbol."
        )
    lines = [f"- {rel} (score {score:.3f})" for rel, score in ranked]
    return (
        f"[SEMANTIC_SEARCH RESULT] Top matches for '{query}' by TF-IDF keyword relevance "
        "(NOT embeddings/neural semantic search -- ranked purely on weighted overlap of the literal "
        "query words, so synonyms/paraphrases will not be found; treat this as 'fuzzy multi-keyword "
        "grep', not conceptual understanding):\n" + "\n".join(lines)
    )


SPECS = [
    ToolSpec(
        name="project_index",
        description=(
            "Build (or reuse a cached, mtime-invalidated) lightweight index of the workspace: every file's "
            "path/size plus, for recognized source files, its top-level function/class symbols. Python symbols "
            "are extracted exactly via the stdlib `ast` parser; JS/TS/Go/Rust/Java/C-family/Ruby/PHP symbols are "
            "extracted with best-effort regex heuristics that can miss unusual syntax. Returns a compact "
            "directory-grouped summary (file/symbol counts), not a raw file dump -- use it to decide what to "
            "read next. Pass refresh=true to force a full rescan instead of using the cache."
        ),
        parameters={
            "type": "object",
            "properties": {
                "refresh": {"type": "boolean", "description": "Force a full rescan, ignoring the cache (default false)."},
            },
            "required": [],
        },
        handler=project_index,
        legacy_tag_aliases=("project_index",),
    ),
    ToolSpec(
        name="find_symbol",
        description=(
            "Find where a function or class is defined ('go to definition'), using the cached project index "
            "(built automatically if missing/stale). Returns exact-name matches first, falling back to "
            "closest substring matches if there's no exact hit. Much more targeted than grep for locating a "
            "specific definition, but inherits the index's precision: exact for Python (stdlib ast), "
            "heuristic/regex for other languages."
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Function or class name to locate."}},
            "required": ["name"],
        },
        handler=find_symbol,
        legacy_tag_aliases=("find_symbol",),
    ),
    ToolSpec(
        name="outline_file",
        description=(
            "List the indexed symbols (functions/classes/methods with line numbers) for one file, without "
            "reading its full contents -- useful for previewing a large file's structure before deciding "
            "whether to read_file it. Same precision caveats as project_index."
        ),
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}},
            "required": ["path"],
        },
        handler=outline_file,
        legacy_tag_aliases=("outline_file",),
    ),
    ToolSpec(
        name="semantic_search",
        description=(
            "Rank workspace files by TF-IDF keyword relevance to a query, computed with the stdlib only "
            "(no embeddings, no neural model loaded). This is classic keyword-frequency statistics, NOT true "
            "semantic search: it cannot match synonyms, paraphrases, or conceptual similarity beyond the "
            "literal words in the query and the code. Useful as a 'fuzzy multi-keyword grep across the whole "
            "project' for exploratory questions when you don't know the exact identifier to grep or "
            "find_symbol for."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords describing what you're looking for."},
                "max_results": {"type": "integer", "description": "Maximum number of ranked files to return (default 10)."},
            },
            "required": ["query"],
        },
        handler=semantic_search,
        legacy_tag_aliases=("semantic_search", "embedding_index"),
    ),
]
