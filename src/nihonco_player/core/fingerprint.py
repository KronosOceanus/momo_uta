#!/usr/bin/env python3
"""音频指纹：和路径无关的歌曲身份。

指纹 = sha1(时长 + 文件大小 + 25%/50%/75% 处各 32KB 的哈希)[:12]

· 移动/改名/换机器：文件字节不变 → 指纹不变
· 同一段音频两份拷贝：指纹相同（共享同一份标注）
· 重新压制/剪辑：字节变 → 指纹变（视为另一段音频）
· 重新打标签：文件大小和采样位置可能变 → 指纹可能变（已知限制）

结果缓存在 data/cache/fingerprints.json（按路径 + size + mtime 失效）。
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from nihonco_yomi.paths import CACHE

INDEX = CACHE / "fingerprints.json"
INDEX_VERSION = 2
CHUNK = 32 * 1024
POSITIONS = (0.25, 0.5, 0.75)
_LOCK = threading.RLock()
_CACHE: dict | None = None
_DIRTY = False


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            data = json.loads(INDEX.read_text(encoding="utf-8"))
            _CACHE = data if data.get("_v") == INDEX_VERSION else {}
        except Exception:
            _CACHE = {}
    return _CACHE


def paths_for_uids(uids) -> dict[str, list[str]]:
    """从路径→指纹索引反查 uid→仍存在的路径（启动按需加载用）。"""
    wanted = {str(u) for u in uids if u}
    out: dict[str, list[str]] = {}
    with _LOCK:
        idx = _load()
        for path, rec in idx.items():
            if path == "_v" or not isinstance(rec, dict):
                continue
            uid = rec.get("fp")
            if uid not in wanted:
                continue
            p = Path(path).expanduser()
            if p.is_file():
                out.setdefault(str(uid), []).append(str(p))
    for paths in out.values():
        paths.sort()
    return out


def prune(valid_paths) -> None:
    """全量扫描后删掉不再存在的路径记录。"""
    global _DIRTY
    valid = {str(p) for p in valid_paths}
    with _LOCK:
        idx = _load()
        for path in list(idx):
            if path == "_v" or path in valid:
                continue
            idx.pop(path, None)
            _DIRTY = True


def flush() -> None:
    global _DIRTY
    with _LOCK:
        if not _DIRTY or _CACHE is None:
            return
        try:
            INDEX.parent.mkdir(parents=True, exist_ok=True)
            data = {"_v": INDEX_VERSION, **_CACHE}
            INDEX.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            _DIRTY = False
        except Exception:
            pass


def _duration(path: Path) -> float | None:
    try:
        from mutagen import File as MFile
        info = MFile(str(path))
        if info is not None and getattr(info, "info", None):
            return float(info.info.length)
    except Exception:
        pass
    # mutagen 读不了 wav 时（没有 INFO 块）用标准库补
    try:
        if path.suffix.lower() == ".wav":
            import wave
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / float(w.getframerate())
    except Exception:
        pass
    return None


def _samples(path: Path, size: int) -> bytes:
    out = bytearray()
    with path.open("rb") as fh:
        if size <= CHUNK * len(POSITIONS):
            fh.seek(0)
            out += fh.read(CHUNK * len(POSITIONS))
        else:
            for pos in POSITIONS:
                off = int(size * pos) - CHUNK // 2
                fh.seek(max(0, min(off, size - CHUNK)))
                out += fh.read(CHUNK)
    return bytes(out)


def fingerprint(audio: str | Path, force: bool = False) -> str:
    """返回 12 位十六进制指纹；读不了文件时退回路径哈希（保证不抛错）。"""
    global _DIRTY
    p = Path(audio)
    try:
        st = p.stat()
        key = str(p)
        with _LOCK:
            idx = _load()
            rec = idx.get(key)
            if not force and rec and rec.get("size") == st.st_size and rec.get("mtime") == st.st_mtime:
                return rec["fp"]
        dur = _duration(p)
        data = _samples(p, st.st_size)
        dur_s = f"{dur:.1f}" if dur is not None else "na"
        raw = f"{dur_s}|{st.st_size}|".encode() + data
        fp = hashlib.sha1(raw).hexdigest()[:12]
        with _LOCK:
            _load()[key] = {"size": st.st_size, "mtime": st.st_mtime, "fp": fp}
            _DIRTY = True
        return fp
    except Exception:
        # 读不了（测试占位文件、损坏文件等）：退回路径哈希，保证有稳定 id
        return hashlib.md5(str(p).encode()).hexdigest()[:12]
