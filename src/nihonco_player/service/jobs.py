#!/usr/bin/env python3
"""任务编排：把 vocals / match / rebuild 接到统一的 job 表。"""
from __future__ import annotations

import time

from nihonco_yomi.config import JOB
from ..core import jobs as JOBS
from ..core import library as LIB
from ..core import vocals as VOC
from . import song as SONGS

KINDS = {"vocals", "match", "rebuild"}


def start(kind: str, uid=None) -> dict:
    kind = str(kind or "")
    if kind not in KINDS:
        raise ValueError("未知任务类型：" + kind)

    if kind == "rebuild":
        key = "library"

        def run_rebuild():
            if not LIB.LAST_MISSING:
                return {"library": len(LIB.snapshot()), "missing": 0, "recovered": 0}
            return LIB.rebuild_library()

        return JOBS.start(kind, key, run_rebuild)

    item = LIB.resolve(uid) if uid is not None else None
    if not item:
        raise ValueError("没有这首歌")
    idx = item.get("uid")

    if kind == "vocals":
        uid = item["uid"]
        audio = item["file"]

        def run_vocals():
            VOC.ensure(uid, audio)
            # 超时由 vocals worker 负责：排队超时/子进程超时会写 failed。
            # 这里只等待真实终态，不再自己宣告超时却留下仍在跑的子进程。
            while True:
                st = VOC.status(uid)
                if st.get("state") == "done":
                    return st
                if st.get("state") == "failed":
                    raise RuntimeError(st.get("error") or "人声分离失败")
                time.sleep(float(JOB["vocals_poll_ms"]) / 1000)

        return JOBS.start(kind, uid, run_vocals)

    def run_match():
        SONGS.lazy_match(item)
        return {"idx": str(idx)}

    return JOBS.start(kind, str(idx), run_match)
