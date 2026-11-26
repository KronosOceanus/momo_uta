#!/usr/bin/env python3
"""把 app 的 stdout / stderr 同时写一份到 data/cache/app.log。

目的：界面上只显示"失败"时，能在日志里看到完整 traceback。
"""
from __future__ import annotations

import io
import sys
import threading
import time
import traceback
from pathlib import Path

from momo_yomi.config import APP
from momo_yomi.paths import CACHE
from momo_player.core import diag

MAX_BYTES = int(APP["log_max_bytes"])
KEEP_FILES = int(APP.get("log_keep_files", 3) or 3)
WARN_COOLDOWN = 60.0


def _rotate_files(log: Path, keep: int = KEEP_FILES) -> None:
    """启动/运行中轮转：app.log.2→.3，app.log.1→.2，app.log→.1。"""
    keep = max(1, int(keep))
    for i in range(keep - 1, 0, -1):
        src = log.with_name(f"{log.name}.{i}")
        dst = log.with_name(f"{log.name}.{i + 1}")
        if src.is_file():
            try:
                src.replace(dst)
            except OSError:
                pass
    if log.is_file():
        try:
            log.replace(log.with_name(f"{log.name}.1"))
        except OSError:
            pass
    # 清理超出保留数量的旧文件。
    for old in log.parent.glob(f"{log.name}.*"):
        try:
            n = int(old.name.rsplit(".", 1)[1])
        except (IndexError, ValueError):
            continue
        if n > keep:
            try:
                old.unlink()
            except OSError:
                pass


class _LogSink:
    """共享的日志文件；运行中超过上限时轮转，轮转过程中加锁。"""

    def __init__(self, path: Path, max_bytes: int, keep: int):
        self.path = Path(path)
        self.max_bytes = max(0, int(max_bytes))
        self.keep = max(1, int(keep))
        self.lock = threading.RLock()
        self._warned = False
        self._warn_at = 0.0
        self.file = open(self.path, "a", encoding="utf-8", buffering=1)

    def _warn(self, message: str) -> None:
        now = time.monotonic()
        if self._warned and now - self._warn_at < WARN_COOLDOWN:
            return
        self._warned = True
        self._warn_at = now
        try:
            print(f"[log] {message}", file=sys.__stderr__)
        except Exception:
            pass

    def _recovered(self) -> None:
        self._warned = False
        self._warn_at = 0.0

    def write(self, s: str) -> int:
        with self.lock:
            try:
                if self.file is None:
                    self._warn("日志文件不可用，后续日志仅写 stderr")
                    return len(s)
                self.file.write(s)
                self.file.flush()
                self._recovered()
                if self.max_bytes and self.file.tell() >= self.max_bytes:
                    self._rotate()
            except Exception as e:
                self._warn(f"写日志失败：{e}")
            return len(s)

    def _rotate(self) -> None:
        try:
            self.file.close()
        except Exception:
            pass
        try:
            _rotate_files(self.path, self.keep)
        except Exception as e:
            self._warn(f"日志轮转失败：{e}")
        try:
            self.file = open(self.path, "a", encoding="utf-8", buffering=1)
            self._recovered()
        except Exception as e:
            self.file = None
            self._warn(f"日志重新打开失败：{e}")

    def flush(self) -> None:
        with self.lock:
            try:
                if self.file is not None:
                    self.file.flush()
            except Exception:
                pass

    def close(self) -> None:
        with self.lock:
            try:
                if self.file is not None:
                    self.file.close()
            except Exception:
                pass
            self.file = None


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


_SINK: _LogSink | None = None


def setup() -> Path:
    """开始记录，返回日志路径。重复调用不会重复打开文件。"""
    global _SINK
    if _SINK is not None:
        return _SINK.path
    logdir = CACHE
    logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / "app.log"
    if log.exists() and log.stat().st_size > MAX_BYTES:
        _rotate_files(log, KEEP_FILES)
    _SINK = _LogSink(log, MAX_BYTES, KEEP_FILES)
    diag.set_writer(_SINK.write)
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.__stdout__, _SINK)
        sys.stderr = _Tee(sys.__stderr__, _SINK)
    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====", file=sys.stderr)

    def _thread_hook(args):                       # 后台线程里未捕获的异常也写进来
        print(f"线程 {getattr(args.thread, 'name', '?')} 异常：", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = _thread_hook
    return log


def log_exception(exc_type, exc, tb) -> None:
    traceback.print_exception(exc_type, exc, tb)
