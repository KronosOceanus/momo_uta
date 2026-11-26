#!/usr/bin/env python3
"""每首歌的界面状态（只影响播放，不改文件）。

现在只有一个字段：offset（整体偏移，秒）。
文件 data/curated/song_meta.json：{ "<uid>": {"offset": 0.4} }
"""
from __future__ import annotations


from momo_yomi.paths import ROOT

from . import fsio as FS

FILE = ROOT / "data" / "curated" / "song_meta.json"
LOCK = FILE.with_suffix(".lock")


def set_file(path) -> None:
    global FILE, LOCK
    from pathlib import Path as _P
    FILE = _P(path)
    LOCK = FILE.with_suffix(".lock")


def _locked():
    return FS.locked(LOCK)


def load() -> dict:
    raw = FS.read_json(FILE, {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def get(key: str, field: str, default=None):
    return load().get(key, {}).get(field, default)


def put(key: str, **fields) -> None:
    with _locked():
        d = load()
        d.setdefault(key, {}).update(fields)
        FS.atomic_write_json(FILE, d, indent=1)
