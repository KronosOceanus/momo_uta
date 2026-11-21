#!/usr/bin/env python3
"""曲库条目快照：路径 → 可复用的条目元信息。

只缓存可重建信息（uid/标题/歌手/大小/mtime 等），不存 idx、播放状态。
启动按需加载时用它避免逐条重算指纹和重新拆文件名。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from nihonco_yomi.paths import CACHE

INDEX = CACHE / "library_index.json"
VERSION = 1
_FIELDS = ("key", "uid", "stem", "orig", "title", "artist",
           "group", "source", "lang", "suspect")
_lock = threading.RLock()
_data: dict | None = None
_dirty = False


def _load() -> dict:
    global _data
    if _data is None:
        try:
            raw = json.loads(INDEX.read_text(encoding="utf-8"))
            _data = raw.get("records", {}) if raw.get("_v") == VERSION else {}
        except Exception:
            _data = {}
    return _data


def get(path: str | Path) -> dict | None:
    p = Path(path)
    try:
        st = p.stat()
    except Exception:
        return None
    with _lock:
        rec = _load().get(str(p))
    if not rec or rec.get("size") != st.st_size or rec.get("mtime") != st.st_mtime:
        return None
    return dict(rec)


def put(entry: dict) -> None:
    global _dirty
    p = Path(entry.get("file") or "")
    try:
        st = p.stat()
    except Exception:
        return
    rec = {k: entry.get(k) for k in _FIELDS if k in entry}
    rec.update({"size": st.st_size, "mtime": st.st_mtime})
    with _lock:
        _load()[str(p)] = rec
        _dirty = True


def paths_by_uid() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with _lock:
        for path, rec in _load().items():
            if rec.get("uid"):
                out.setdefault(str(rec["uid"]), []).append(path)
    for paths in out.values():
        paths.sort()
    return out


def flush() -> None:
    global _dirty
    with _lock:
        if not _dirty or _data is None:
            return
        try:
            INDEX.parent.mkdir(parents=True, exist_ok=True)
            tmp = INDEX.with_suffix(".tmp")
            tmp.write_text(json.dumps({"_v": VERSION, "records": _data},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(INDEX)
            _dirty = False
        except Exception:
            pass
