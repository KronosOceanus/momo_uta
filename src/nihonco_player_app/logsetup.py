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

MAX_BYTES = 2 * 1024 * 1024


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


def setup() -> Path:
    """开始记录，返回日志路径。重复调用只会记录一次。"""
    root = Path(__file__).resolve().parents[2]
    logdir = root / "data" / "cache"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / "app.log"
    if log.exists() and log.stat().st_size > MAX_BYTES:      # 简单轮转
        log.replace(log.with_suffix(".log.1"))
    fh = open(log, "a", encoding="utf-8", buffering=1)
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.__stdout__, fh)
        sys.stderr = _Tee(sys.__stderr__, fh)
    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====", file=sys.stderr)

    def _thread_hook(args):                       # 后台线程里未捕获的异常也写进来
        print(f"线程 {getattr(args.thread, 'name', '?')} 异常：", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = _thread_hook
    return log


def log_exception(exc_type, exc, tb) -> None:
    traceback.print_exception(exc_type, exc, tb)
