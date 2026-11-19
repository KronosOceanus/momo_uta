#!/usr/bin/env python3
"""静态文件与音频流（支持 Range）。"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent.parent / "static"
CTYPE = {".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8",
         ".html": "text/html; charset=utf-8"}


def static_file(path: str):
    """返回 (bytes/str, content_type)；找不到返回 None。"""
    rel = path[len("/static/"):] if path.startswith("/static/") else path
    if ".." in rel:
        return None
    f = STATIC / rel
    if not f.is_file():
        return None
    return f.read_text(encoding="utf-8"), CTYPE.get(f.suffix, "application/octet-stream")


def audio_info(file: str, range_header: str | None):
    """计算音频响应参数：(code, start, end, size, ctype, content_range)。"""
    f = Path(file)
    if not f.is_file():
        return None
    size = f.stat().st_size
    start, end, code = 0, size - 1, 200
    rng = range_header or ""
    if rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        try:
            start = int(a) if a else 0
            end = int(b) if b else size - 1
            code = 206
        except ValueError:
            start, end, code = 0, size - 1, 200
    end = min(end, size - 1)
    ctype = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
             ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg"
             }.get(f.suffix.lower(), "application/octet-stream")
    return code, start, end, size, ctype, (f"bytes {start}-{end}/{size}" if code == 206 else None)
