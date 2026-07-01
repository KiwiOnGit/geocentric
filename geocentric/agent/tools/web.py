"""Web search / browse / download tools.

search_duckduckgo's scraping logic is ported from geocentric/server.py
(no API keys, no external search-API dependency, HTML-scrapes DuckDuckGo
then falls back to Bing) since it's self-contained and already correct.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any

from . import ToolContext, ToolSpec
from ..workspace import resolve_in_workspace


def _clean_result_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _normalize_result_url(raw_url: str) -> str:
    raw_url = html.unescape(urllib.parse.unquote(raw_url or ""))
    parsed = urllib.parse.urlparse(raw_url)
    query_values = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query_values and query_values["uddg"]:
        return urllib.parse.unquote(query_values["uddg"][0])
    return raw_url


def _request_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(1_200_000).decode("utf-8", errors="ignore")


def _parse_duckduckgo(body: str, max_results: int) -> list[dict[str, str]]:
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
        url = _normalize_result_url(link_match.group(1))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        title = _clean_result_text(link_match.group(2))
        if title:
            results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


def _search_duckduckgo(query: str, max_results: int = 5) -> list[dict[str, str]]:
    query = re.sub(r"\s+", " ", query or "").strip()
    if not query:
        return []
    sources = [
        "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
        "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query),
    ]
    for url in sources:
        try:
            body = _request_text(url)
            results = _parse_duckduckgo(body, max_results)
            if results:
                return results
        except Exception:
            continue
    return []


def web_search(args: dict[str, Any], ctx: ToolContext) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "[WEB SEARCH ERROR] No query provided."
    if ctx.on_status:
        ctx.on_status(f"Searching the web: {query}")
    results = _search_duckduckgo(query, max_results=int(args.get("max_results", 5)))
    if not results:
        return f"[WEB SEARCH RESULT] No results found for '{query}'."
    lines = [f"- {r['title']}: {r['url']}" for r in results]
    return f"[WEB SEARCH RESULT] Results for '{query}':\n" + "\n".join(lines)


def browse_url(args: dict[str, Any], ctx: ToolContext) -> str:
    url = str(args.get("url", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"[BROWSE URL ERROR] Unsupported URL scheme for '{url}'. Use http or https."
    if ctx.on_status:
        ctx.on_status(f"Browsing URL: {url}")
    try:
        body = _request_text(url, timeout=15)
    except Exception as exc:
        return f"[BROWSE URL ERROR] Failed to fetch {url}: {exc}"
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", body, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    max_chars = int(args.get("max_chars", 12000))
    return f"[BROWSE URL RESULT] {url}\n{text[:max_chars]}"


def download_url(args: dict[str, Any], ctx: ToolContext) -> str:
    url = str(args.get("url", "")).strip()
    rel = str(args.get("path", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"[DOWNLOAD URL ERROR] Unsupported URL scheme for '{url}'."
    if ctx.on_status:
        ctx.on_status(f"Downloading: {url}")
    target = resolve_in_workspace(ctx.workspace_dir, rel)
    max_bytes = 50 * 1024 * 1024
    req = urllib.request.Request(url, headers={"User-Agent": "Geocentric-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        return f"[DOWNLOAD URL ERROR] Download exceeded {max_bytes} bytes."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return f"[DOWNLOAD URL SUCCESS] Saved {len(data)} bytes from {url} to {rel}"


SPECS = [
    ToolSpec(
        name="web_search",
        description="Search the web and return a list of relevant page titles and URLs.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"],
        },
        handler=web_search,
        legacy_tag_aliases=("search", "web_search"),
    ),
    ToolSpec(
        name="browse_url",
        description="Fetch a URL and return its visible text content.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
            "required": ["url"],
        },
        handler=browse_url,
        legacy_tag_aliases=("browse_url",),
    ),
    ToolSpec(
        name="download_url",
        description="Download a URL's contents into a file in the workspace.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}, "path": {"type": "string"}},
            "required": ["url", "path"],
        },
        handler=download_url,
        requires_approval=True,
        legacy_tag_aliases=("download_url",),
    ),
]
