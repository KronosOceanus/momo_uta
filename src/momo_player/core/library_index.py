#!/usr/bin/env python3
"""曲库条目快照：路径 → 可复用的条目元信息。

只缓存可重建信息（uid/标题/歌手/大小/mtime 等），不存 idx、播放状态。
启动按需加载时用它避免逐条重算指纹和重新拆文件名。
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from momo_yomi.paths import CACHE

from . import diag
from . import fsio as FS

INDEX = CACHE / "library_index.json"


def _source_version() -> str:
    try:
        return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "1"


VERSION = _source_version()
_FIELDS = ("key", "uid", "stem", "orig", "title", "artist",
           "group", "source", "lang", "suspect")
_lock = threading.RLock()
_data: dict | None = None
_dirty = False


def _load() -> dict:
    global _data
    if _data is None:
        raw = FS.read_json(INDEX, {}) or {}
        _data = ({"_meta": raw.get("meta") or {}, **raw.get("records", {})}
                 if raw.get("_v") == VERSION else {})
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


def meta() -> dict:
    with _lock:
        return dict((_load().get("_meta") or {}))


def set_meta(data: dict) -> None:
    global _dirty
    with _lock:
        recs = _load()
        recs["_meta"] = dict(data)
        _dirty = True


def prune(valid_paths) -> None:
    """全量扫描后删掉不再存在的路径记录。"""
    global _dirty
    valid = {str(p) for p in valid_paths}
    with _lock:
        recs = _load()
        for path in list(recs):
            if path.startswith("_") or path in valid:
                continue
            recs.pop(path, None)
            _dirty = True


def prune_paths(paths) -> None:
    global _dirty
    with _lock:
        recs = _load()
        for raw in paths:
            key = str(raw)
            if key in recs:
                recs.pop(key, None)
                _dirty = True


def paths_by_uid() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with _lock:
        for path, rec in _load().items():
            if path.startswith("_") or not isinstance(rec, dict):
                continue
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
            recs = {k: v for k, v in _data.items() if not k.startswith("_")}
            FS.atomic_write_json(INDEX, {"_v": VERSION, "meta": _data.get("_meta") or {},
                                         "records": recs}, indent=None)
            _dirty = False
        except Exception as e:
            diag.log("library", f"index flush failed: {e}")
