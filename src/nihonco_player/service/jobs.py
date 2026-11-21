#!/usr/bin/env python3
"""任务编排：把 vocals / match / rebuild 接到统一的 job 表。"""
from __future__ import annotations

import time

from ..core import jobs as JOBS
from ..core import library as LIB
from ..core import vocals as VOC
from ..core.library import CACHE
from . import song as SONGS

KINDS = {"vocals", "match", "rebuild"}


def start(kind: str, idx=None) -> dict:
    kind = str(kind or "")
    if kind not in KINDS:
        raise ValueError("未知任务类型：" + kind)

    if kind == "rebuild":
        key = "library"

        def run_rebuild():
            if not LIB.LAST_MISSING:
                return {"library": len(CACHE), "missing": 0, "recovered": 0}
            return LIB.rebuild_library()

        return JOBS.start(kind, key, run_rebuild)

    item = CACHE.get(str(idx)) if idx is not None else None
    if not item:
        raise ValueError("没有这首歌")

    if kind == "vocals":
        uid = item["uid"]
        audio = item["file"]

        def run_vocals():
            VOC.ensure(uid, audio)
            for _ in range(400):
                st = VOC.status(uid)
                if st.get("state") == "done":
                    return st
                if st.get("state") == "failed":
                    raise RuntimeError(st.get("error") or "人声分离失败")
                time.sleep(1.5)
            raise TimeoutError("人声分离超时")

        return JOBS.start(kind, uid, run_vocals)

    def run_match():
        SONGS.lazy_match(item)
        return {"idx": str(idx)}

    return JOBS.start(kind, str(idx), run_match)
