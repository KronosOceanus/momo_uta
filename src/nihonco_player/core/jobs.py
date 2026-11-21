#!/usr/bin/env python3
"""轻量内存任务表：长任务的统一状态源。

任务本身仍由各自的线程/队列执行；这里只负责：
  · 生成 job id
  · 同一 kind+key 正在跑时复用
  · queued/running/done/failed 状态
  · 结果/错误快照
进程退出后清空；完成结果本身应写入各自的缓存。
"""
from __future__ import annotations

import threading
import time
import uuid

from nihonco_yomi.config import JOB

from . import diag

_lock = threading.RLock()
_jobs: dict[str, dict] = {}
MAX_DONE = int(JOB["keep_done"])


def _copy(job: dict) -> dict:
    return dict(job)


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return _copy(job) if job else None


def find_active(kind: str, key: str) -> dict | None:
    with _lock:
        for job in _jobs.values():
            if job["kind"] == kind and str(job["key"]) == str(key) \
                    and job["state"] in ("queued", "running"):
                return _copy(job)
    return None


def start(kind: str, key, runner) -> dict:
    """启动后台任务；runner 返回结果，异常转为 failed。"""
    active = find_active(kind, str(key))
    if active:
        return active
    job_id = uuid.uuid4().hex
    now = time.time()
    job = {"id": job_id, "kind": kind, "key": str(key), "state": "queued",
           "stage": "", "error": None, "result": None,
           "since": now, "updated": now}
    with _lock:
        _jobs[job_id] = job
        _prune_locked()

    def run():
        with _lock:
            job["state"] = "running"
            job["updated"] = time.time()
        try:
            result = runner()
            with _lock:
                job["state"] = "done"
                job["result"] = result
                job["updated"] = time.time()
        except Exception as e:
            diag.exception("job", e, kind=kind, key=key)
            with _lock:
                job["state"] = "failed"
                job["error"] = str(e)[:500]
                job["updated"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
    return _copy(job)


def _prune_locked() -> None:
    done = [j for j in _jobs.values() if j["state"] in ("done", "failed")]
    if len(done) <= MAX_DONE:
        return
    done.sort(key=lambda j: j["updated"])
    for j in done[:len(done) - MAX_DONE]:
        _jobs.pop(j["id"], None)
