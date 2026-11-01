"""Optional EasyImages post-processing for Gradio Markdown exports."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from .artifacts import RunArtifacts

_INTERVAL = 0.6
_RATE_LOCK = threading.Lock()
_LAST_STARTED = 0.0
# Markdown image destinations and HTML image src are collected only outside fenced code.
_INLINE_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
_REF_IMAGE = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")
_REF_DEF = re.compile(r"(?m)^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1[^>]*>", re.I | re.S)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def configured() -> bool:
    """Return whether the WebUI has both optional image-host settings."""
    return bool(os.getenv("EASYIMAGES_API_URL", "").strip() and os.getenv("EASYIMAGES_TOKEN", "").strip())


def _endpoint() -> str:
    root = os.environ["EASYIMAGES_API_URL"].strip().rstrip("/")
    parsed = urlsplit(root)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("EASYIMAGES_API_URL must be an HTTPS site URL")
    if parsed.path not in {"", "/", "/api/index.php"}:
        raise ValueError("EASYIMAGES_API_URL must be a site root")
    return f"{parsed.scheme}://{parsed.netloc}/api/index.php"


def _request_slot() -> None:
    global _LAST_STARTED
    with _RATE_LOCK:
        wait = _INTERVAL - (time.monotonic() - _LAST_STARTED)
        if wait > 0:
            time.sleep(wait)
        _LAST_STARTED = time.monotonic()


def _upload(path: Path) -> str:
    endpoint = _endpoint()
    token = os.environ["EASYIMAGES_TOKEN"].strip()
    for attempt in range(3):
        _request_slot()
        try:
            with path.open("rb") as image:
                response = requests.post(endpoint, data={"token": token}, files={"image": (path.name, image)}, timeout=30, allow_redirects=False)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            raise ValueError(f"Network failure while uploading {path.name}") from exc
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "")
            delay = float(retry) if retry.isdigit() else 10.0
            if attempt < 2:
                time.sleep(min(max(delay, 0.6), 120))
                continue
            raise ValueError("HTTP 429: image host rate limited the upload")
        if response.status_code in {500, 502, 503, 504} and attempt < 2:
            time.sleep(1 + attempt * 2)
            continue
        if response.status_code != 200:
            raise ValueError(f"Image host returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Image host returned a non-JSON response (possible challenge)") from exc
        if not isinstance(data, dict) or data.get("result") != "success" or data.get("code") != 200:
            raise ValueError("Image host rejected the upload")
        url = data.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).netloc:
            raise ValueError("Image host returned an invalid image URL")
        return url
    raise ValueError("Upload failed")


def _safe_local_path(root: Path, raw: str) -> Path | None:
    link = html.unescape(raw.strip().strip("<>"))
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or link.startswith(("/", "\\", "#")):
        return None
    decoded = unquote(parsed.path)
    if not decoded.startswith("images/") or "\\" in decoded:
        return None
    candidate = (root / decoded).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"Missing or unsafe local image: {decoded}")
    return candidate


def _references(markdown: str, root: Path) -> tuple[list[tuple[int, int, str, Path]], list[Path]]:
    """Collect address spans, excluding fenced code and unrelated remote URLs."""
    masked = list(markdown)
    fence_char = ""
    fence_length = 0
    offset = 0
    for line in markdown.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if marker:
            found = marker.group(1)
            if not fence_char:
                fence_char, fence_length = found[0], len(found)
            elif found[0] == fence_char and len(found) >= fence_length:
                fence_char, fence_length = "", 0
            masked[offset:offset + len(line)] = " " * len(line)
        elif fence_char:
            masked[offset:offset + len(line)] = " " * len(line)
        offset += len(line)
    visible = "".join(masked)
    spans: list[tuple[int, int, str, Path]] = []
    defs = {m.group(1).strip().casefold(): m for m in _REF_DEF.finditer(visible)}
    used_defs: set[str] = set()
    for match in _REF_IMAGE.finditer(visible):
        used_defs.add(match.group(1).strip().casefold())
    for match in _INLINE_IMAGE.finditer(visible):
        path = _safe_local_path(root, match.group(1))
        if path is not None:
            spans.append((match.start(1), match.end(1), match.group(1), path))
    for name in used_defs:
        definition = defs.get(name)
        if definition is not None:
            path = _safe_local_path(root, definition.group(2))
            if path is not None:
                spans.append((definition.start(2), definition.end(2), definition.group(2), path))
    for match in _HTML_IMAGE.finditer(visible):
        path = _safe_local_path(root, match.group(2))
        if path is not None:
            spans.append((match.start(2), match.end(2), match.group(2), path))
    unique = list(dict.fromkeys(part[3] for part in spans))
    return spans, unique


def _write_json(path: Path, data: dict[str, object]) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def generate(artifacts: RunArtifacts, *, allowed_root: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    """Upload referenced local images and return a standalone Markdown path."""
    if not configured():
        raise ValueError("EasyImages is not configured")
    root = artifacts.root.resolve()
    if not root.is_relative_to(allowed_root.resolve()) or not artifacts.markdown_path.is_file():
        raise ValueError("Invalid or missing conversion result")
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    spans, images = _references(markdown, root)
    cache_path = artifacts.downloads_dir / "easyimages_upload_state.json"
    output = artifacts.downloads_dir / f"{artifacts.stem}.md"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    urls: dict[Path, str] = {}
    total = len(images)
    for index, image in enumerate(images, 1):
        relative = image.relative_to(root).as_posix()
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        old = cache.get(relative)
        if isinstance(old, dict) and old.get("sha256") == digest and isinstance(old.get("url"), str) and old["url"].startswith("https://"):
            urls[image] = old["url"]
        else:
            urls[image] = _upload(image)
            cache[relative] = {"sha256": digest, "url": urls[image]}
            _write_json(cache_path, cache)
        if progress is not None:
            progress(index, total)
    for start, end, original, image in reversed(sorted(spans, key=lambda item: item[0])):
        replacement = urls[image]
        if original.startswith("<") and original.endswith(">"):
            replacement = f"<{replacement}>"
        markdown = markdown[:start] + replacement + markdown[end:]
    pending = output.with_suffix(".tmp")
    pending.write_text(markdown, encoding="utf-8")
    pending.replace(output)
    return output


__all__ = ["configured", "generate"]
