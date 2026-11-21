#!/usr/bin/env python3
"""单行注音结果缓存：只缓存显示字段，不碰权威歌词。

key = 缓存版本 + 行文本 + stored 注音
value = line_fields() 的 ruby / rm / ky / rmH / kyH
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from nihonco_yomi.paths import CACHE

CACHE_DIR = CACHE / "annotations"
VERSION = 1
_FIELDS = ("ruby", "rm", "ky", "rmH", "kyH")


def _stored_json(stored) -> str:
    return json.dumps(stored or [], ensure_ascii=False, separators=(",", ":"))


def _key(text: str, stored) -> str:
    h = hashlib.sha1()
    h.update(str(VERSION).encode())
    h.update(b"\0")
    h.update(text.encode("utf-8"))
    h.update(b"\0")
    h.update(_stored_json(stored).encode("utf-8"))
    return h.hexdigest()


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@lru_cache(maxsize=4096)
def _memory(key: str, text: str, stored_json: str) -> dict:
    from .annotation import line_fields
    return line_fields(text, json.loads(stored_json) if stored_json != "[]" else None)


def _valid(obj) -> bool:
    return isinstance(obj, dict) and obj.get("v") == VERSION \
        and isinstance(obj.get("fields"), dict) \
        and all(k in obj["fields"] for k in _FIELDS)


def line_fields(text: str, stored=None) -> dict:
    """带磁盘 + 内存缓存的 line_fields；失败时回退到实时计算。"""
    text = str(text or "")
    if not text:
        return {}
    sj = _stored_json(stored)
    key = _key(text, stored)
    p = _path(key)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if _valid(raw):
            return dict(raw["fields"])
    except Exception:
        pass
    fields = dict(_memory(key, text, sj))
    try:
        _atomic_json(p, {"v": VERSION, "fields": fields})
    except Exception:
        pass
    return fields


def clear_memory() -> None:
    _memory.cache_clear()
