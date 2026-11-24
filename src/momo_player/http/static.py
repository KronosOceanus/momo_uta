#!/usr/bin/env python3
"""静态文件与音频流（支持 Range）。"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent.parent / "static"
CTYPE = {".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8",
         ".html": "text/html; charset=utf-8"}


def static_file(path: str):
    """返回 (bytes/str, content_type)；找不到/越界返回 None。"""
    rel = path[len("/static/"):] if path.startswith("/static/") else path
    if not rel or ".." in rel:
        return None
    try:
        base = STATIC.resolve()
        f = (base / rel).resolve()
    except (OSError, RuntimeError):
        return None
    if f != base and base not in f.parents:
        return None
    if not f.is_file():
        return None
    try:
        return f.read_text(encoding="utf-8"), CTYPE.get(f.suffix, "application/octet-stream")
    except (OSError, UnicodeError):
        return None


def audio_info(file: str, range_header: str | None):
    """计算音频响应参数：(code, start, end, size, ctype, content_range)。"""
    f = Path(file)
    if not f.is_file():
        return None
    size = f.stat().st_size
    ctype = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
             ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg"
             }.get(f.suffix.lower(), "application/octet-stream")
    rng = (range_header or "").strip()
    if not rng:
        return 200, 0, size - 1, size, ctype, None
    if not rng.startswith("bytes=") or "," in rng:
        return 416, 0, -1, size, ctype, f"bytes */{size}"
    spec = rng[6:].strip()
    if "-" not in spec:
        return 416, 0, -1, size, ctype, f"bytes */{size}"
    a, b = spec.split("-", 1)
    try:
        if not a:
            suffix = int(b)
            if suffix <= 0 or size <= 0:
                return 416, 0, -1, size, ctype, f"bytes */{size}"
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(a)
            end = int(b) if b else size - 1
            if start < 0 or start >= size or end < start:
                return 416, 0, -1, size, ctype, f"bytes */{size}"
            end = min(end, size - 1)
    except ValueError:
        return 416, 0, -1, size, ctype, f"bytes */{size}"
    return 206, start, end, size, ctype, f"bytes {start}-{end}/{size}"
