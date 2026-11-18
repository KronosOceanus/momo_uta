#!/usr/bin/env python3
"""每首歌的界面状态（只影响播放，不改文件）。

现在只有一个字段：offset（整体偏移，秒）。
文件 data/curated/song_meta.json：{ "<song key>": {"offset": 0.4} }
"""
from __future__ import annotations

import contextlib
import fcntl
import json
from pathlib import Path

from nihonco_yomi.paths import ROOT

FILE = ROOT / "data" / "curated" / "song_meta.json"
LOCK = FILE.with_suffix(".lock")


def set_file(path) -> None:
    global FILE, LOCK
    from pathlib import Path as _P
    FILE = _P(path)
    LOCK = FILE.with_suffix(".lock")


@contextlib.contextmanager
def _locked():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get(key: str, field: str, default=None):
    return load().get(key, {}).get(field, default)


def put(key: str, **fields) -> None:
    with _locked():
        d = load()
        d.setdefault(key, {}).update(fields)
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
