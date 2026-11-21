#!/usr/bin/env python3
"""文件读写小层：原子写、JSON、跨线程/跨进程文件锁。

只统一“怎么写文件”和“怎么串行”，不规定谁有资格写。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - macOS/Linux target
    fcntl = None

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_depth: dict[str, int] = {}
_handles: dict[str, object] = {}


def read_json(path: str | Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """同目录临时文件 + fsync + os.replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str | Path, obj, *, indent: int | None = 1) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))


@contextlib.contextmanager
def locked(lock_path: str | Path):
    """线程内可重入、进程间 fcntl 互斥。lock_path 就是锁文件路径。"""
    key = str(Path(lock_path))
    with _guard:
        rl = _locks.setdefault(key, threading.RLock())
    with rl:
        with _guard:
            depth = _depth.get(key, 0)
            if depth == 0:
                Path(key).parent.mkdir(parents=True, exist_ok=True)
                fh = open(key, "a+")
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                _handles[key] = fh
            _depth[key] = depth + 1
        try:
            yield
        finally:
            with _guard:
                depth = _depth.get(key, 1) - 1
                if depth <= 0:
                    _depth.pop(key, None)
                    fh = _handles.pop(key, None)
                    if fh is not None:
                        try:
                            if fcntl is not None:
                                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        finally:
                            fh.close()
                else:
                    _depth[key] = depth
