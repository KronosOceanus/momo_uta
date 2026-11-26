#!/usr/bin/env python3
"""最小诊断日志：追加到 data/cache/app.log，失败也绝不抛。"""
from __future__ import annotations

import time
import traceback

from momo_yomi.paths import CACHE

LOG = CACHE / "app.log"
_WRITER = None


def set_writer(writer) -> None:
    """由 logsetup 注册共享日志 writer；None 表示回退到直接追加。"""
    global _WRITER
    _WRITER = writer


def _write(line: str) -> None:
    if _WRITER is not None:
        try:
            _WRITER(line)
            return
        except Exception:
            pass
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def log(kind: str, msg: str) -> None:
    _write(f"[py {time.strftime('%H:%M:%S')}] [{kind}] {msg}\n")


def exception(category: str, exc: BaseException, **context) -> None:
    """记录完整 traceback；写日志失败也绝不抛。"""
    try:
        ctx = " ".join(f"{k}={v!r}" for k, v in context.items())
        head = f"{type(exc).__name__}: {exc}"
        log(category, (head + "\n" + traceback.format_exc() + (ctx and ("\n" + ctx))).rstrip())
    except Exception:
        pass
