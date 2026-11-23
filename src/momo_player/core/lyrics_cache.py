#!/usr/bin/env python3
"""歌词缓存层：键值、文件路径、命中判断、写入（含本地 lrc）。"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

from momo_yomi.paths import ROOT


CACHE = ROOT / "data" / "cache" / "lyrics"


def set_cache_dir(path) -> None:
    """换缓存目录（测试用）。"""
    global CACHE
    from pathlib import Path as _P
    CACHE = _P(path)



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

