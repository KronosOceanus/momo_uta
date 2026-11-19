#!/usr/bin/env python3
"""读音修改：用户手改的振假名，按歌存储。

文件 data/curated/readings.json：
  { "<song key>": { "12:5": "とこ", ... } }     # 行号:起始偏移 → 读音
"""
from __future__ import annotations

import contextlib
import fcntl
import json
from pathlib import Path

from nihonco_yomi.paths import ROOT

FILE = ROOT / "data" / "curated" / "readings.json"
LOCK = FILE.with_suffix(".lock")


def set_file(path) -> None:
    """换数据文件（测试用）。"""
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


def _save(d: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def for_song(key: str) -> dict:
    return load().get(key, {})


def put(key: str, line: int, start: int, reading: str) -> None:
    with _locked():
        d = load()
        d.setdefault(key, {})[f"{line}:{start}"] = reading
        _save(d)


def pop(key: str) -> dict:
    """取出并删除一首歌的条目（迁移用）。"""
    with _locked():
        d = load()
        got = d.pop(key, {})
        _save(d)
        return got


def clear(key: str) -> None:
    with _locked():
        d = load()
        d.pop(key, None)
        _save(d)
