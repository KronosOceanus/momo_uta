#!/usr/bin/env python3
"""最小诊断日志：追加到 data/cache/app.log，失败也绝不抛。"""
from __future__ import annotations

import time

from nihonco_yomi.paths import CACHE

LOG = CACHE / "app.log"


def log(kind: str, msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[py {time.strftime('%H:%M:%S')}] [{kind}] {msg}\n")
    except Exception:
        pass
