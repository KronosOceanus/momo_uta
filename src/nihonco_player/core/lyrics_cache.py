#!/usr/bin/env python3
"""歌词缓存层：键值、文件路径、命中判断、写入（含本地 lrc）。"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

from nihonco_yomi.paths import ROOT

from .lyrics_text import lang_guess

CACHE = ROOT / "data" / "cache" / "lyrics"


def set_cache_dir(path) -> None:
    """换缓存目录（测试用）。"""
    global CACHE
    from pathlib import Path as _P
    CACHE = _P(path)


def cache_dir():
    return CACHE


def _key(title: str, artist: str) -> str:
    t = unicodedata.normalize("NFKC", title or "").lower()
    a = unicodedata.normalize("NFKC", artist or "").lower()
    return hashlib.md5(f"{t}|{a}".encode()).hexdigest()[:16]


def cache_path(title: str, artist: str) -> Path:
    return CACHE / f"{_key(title, artist)}.json"


def _cached(title: str, artist: str) -> bool:
    p = cache_path(title, artist)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return not d.get("miss")


def write_local_lrc(title: str, artist: str, lrc: str, duration: float = 0.0,
                    name: str | None = None, by: str | None = None,
                    annotations: dict | None = None) -> Path:
    """把本地 .lrc 写进缓存（导入用）。不联网，不改原文件。"""
    p = cache_path(title, artist)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "source": "local-lrc", "id": None,
        "name": name or title, "artist": by or artist,
        "duration": duration, "lrc": lrc, "lang": lang_guess(lrc)[0],
        "title": title, "artist_q": artist,
        **({"nhlrc_annotations": annotations} if annotations else {}),
    }, ensure_ascii=False), encoding="utf-8")
    return p


