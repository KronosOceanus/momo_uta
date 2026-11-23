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

from momo_yomi.config import JOB

from . import diag

_lock = threading.RLock()
_local = threading.local()
_jobs: dict[str, dict] = {}
MAX_DONE = int(JOB["keep_done"])


def _copy(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return _copy(job) if job else None


def start(kind: str, key, runner, cancel=None) -> dict:
    """启动后台任务；同 kind+key 的 queued/running 任务原子复用。"""
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        for job in _jobs.values():
            if job["kind"] == kind and str(job["key"]) == str(key) \
                    and job["state"] in ("queued", "running"):
                return _copy(job)
        job = {"id": job_id, "kind": kind, "key": str(key), "state": "queued",
               "stage": "queued", "error": None, "result": None,
               "since": now, "updated": now, "_cancel": cancel,
               "_cancel_requested": False}
        _jobs[job_id] = job
        _prune_locked()
        snapshot = _copy(job)

    def run():
        _local.job_id = job_id
        try:
            with _lock:
                if job.get("_cancel_requested"):
                    job["state"] = "canceled"
                    job["stage"] = "canceled"
                    job["error"] = "已取消"
                    job["updated"] = time.time()
                    return
                job["state"] = "running"
                job["stage"] = "queued"
                job["updated"] = time.time()
            try:
                result = runner()
                with _lock:
                    if job.get("_cancel_requested"):
                        job["state"] = "canceled"
                        job["stage"] = "canceled"
                        job["error"] = "已取消"
                    else:
                        job["state"] = "done"
                        job["stage"] = "done"
                        job["result"] = result
                    job["updated"] = time.time()
            except Exception as e:
                with _lock:
                    canceled = bool(job.get("_cancel_requested"))
                    job["state"] = "canceled" if canceled else "failed"
                    job["stage"] = job["state"]
                    job["error"] = "已取消" if canceled else str(e)[:500]
                    job["updated"] = time.time()
                if not canceled:
                    diag.exception("job", e, kind=kind, key=key)
        finally:
            _local.job_id = None

    threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
    return snapshot


def set_stage(stage: str) -> None:
    """executor 更新当前任务的实际阶段；state 仍是 job 生命周期。"""
    job_id = getattr(_local, "job_id", None)
    if not job_id:
        return
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["state"] in ("done", "failed", "canceled"):
            return
        job["stage"] = str(stage)
        job["updated"] = time.time()


def active(kind: str | None = None) -> list[dict]:
    with _lock:
        return [_copy(j) for j in _jobs.values()
                if j["state"] in ("queued", "running", "canceling")
                and (kind is None or j["kind"] == kind)]


def cancel(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job["state"] in ("done", "failed", "canceled"):
            return _copy(job)
        job["_cancel_requested"] = True
        job["state"] = "canceling"
        job["stage"] = "canceling"
        job["updated"] = time.time()
        cb = job.get("_cancel")
        out = _copy(job)
    if callable(cb):
        try:
            cb()
        except Exception as e:
            diag.exception("job.cancel", e, job=job_id)
    return out


def cancel_all(kind: str | None = None) -> list[dict]:
    with _lock:
        ids = [j["id"] for j in _jobs.values()
               if j["state"] in ("queued", "running", "canceling")
               and (kind is None or j["kind"] == kind)]
    return [j for j in (cancel(i) for i in ids) if j]


def _prune_locked() -> None:
    done = [j for j in _jobs.values() if j["state"] in ("done", "failed", "canceled")]
    if len(done) <= MAX_DONE:
        return
    done.sort(key=lambda j: j["updated"])
    for j in done[:len(done) - MAX_DONE]:
        _jobs.pop(j["id"], None)
