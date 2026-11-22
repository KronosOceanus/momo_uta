#!/usr/bin/env python3
"""人声分离：demucs 两轨模式跑一次，缓存 16k 单声道人声 + 元数据。

只做三件事：
  1. 队列化调用 demucs（串行，一条一条跑）
  2. 把 vocals.wav 转成 16k 单声道（波形与判定只用它）
  3. 算"有没有人声"的指标，写进 meta.json
"""
from __future__ import annotations

import array
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from queue import Queue

from nihonco_yomi.config import VC
from . import diag
from . import fsio as FS
from nihonco_yomi.paths import VOCALS

TMP_ROOT = VOCALS.parent / "tmp" / "vocals"
MODEL = VC["model"]
MIN_RATIO = VC["ratio_min"]          # 有唱帧占比超过它 → 认为有人声
FRAME = VC["frame_sec"]              # VAD 帧长（秒）
SAMPLE_RATE = VC["sample_rate"]

_queue: Queue = Queue()
_states: dict[str, dict] = {}
_canceled: set[str] = set()
_current: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()
_proc_lock = threading.Lock()
_worker: threading.Thread | None = None


class Cancelled(RuntimeError):
    """用户或任务编排主动取消，不是分离失败。"""


def paths(uid: str) -> tuple[Path, Path, Path]:
    d = VOCALS / uid
    return d, d / "vocals.wav", d / "meta.json"


def _touch(uid: str) -> None:
    m = meta(uid)
    if not m:
        return
    m["last_used"] = int(time.time())
    try:
        _, _, mp = paths(uid)
        FS.atomic_write_json(mp, m, indent=1)
    except Exception:
        pass


def meta(uid: str) -> dict | None:
    _, _, m = paths(uid)
    out = FS.read_json(m, None)
    return out if isinstance(out, dict) else None


def status(uid: str) -> dict:
    m = meta(uid)
    if m:
        return {"state": "done", **m}
    with _lock:
        st = _states.get(uid)
    return dict(st) if st else {"state": "none"}


def ensure(uid: str, audio: str) -> dict:
    """确保这首歌有人声轨：已有缓存直接返回；否则排队（幂等）。"""
    if meta(uid):
        _touch(uid)
        return status(uid)
    with _lock:
        st = _states.get(uid)
        if st and st.get("state") in ("queued", "running", "canceling"):
            return dict(st)
        _canceled.discard(uid)
        _states[uid] = {"state": "queued", "since": time.time()}
        _queue.put((uid, str(audio)))
        _start_worker()
        return dict(_states[uid])


def active() -> list[dict]:
    with _lock:
        return [{"uid": u, **dict(st)} for u, st in _states.items()
                if st.get("state") in ("queued", "running", "canceling")]


def _is_canceled(uid: str | None) -> bool:
    if not uid:
        return False
    with _lock:
        return uid in _canceled


def _kill_proc(uid: str) -> None:
    with _proc_lock:
        p = _current.get(uid)
    if not p:
        return
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def cancel(uid: str, include_running: bool = True) -> dict:
    """取消一首歌的人声任务；queued 直接丢弃，running 杀进程组。"""
    uid = str(uid)
    with _lock:
        st = dict(_states.get(uid) or {})
        state = st.get("state")
        if state not in ("queued", "running", "canceling"):
            return {"ok": True, "uid": uid, "state": state or "none"}
        _canceled.add(uid)
        if state == "queued":
            _states[uid] = {"state": "canceled", "error": "已取消",
                            "since": time.time()}
            return {"ok": True, "uid": uid, "state": "canceled"}
        if state == "running" and not include_running:
            _canceled.discard(uid)
            return {"ok": False, "uid": uid, "state": state,
                    "error": "任务正在执行"}
        _states[uid] = {"state": "canceling", "since": time.time()}
    _kill_proc(uid)
    return {"ok": True, "uid": uid, "state": "canceling"}


def cancel_all(include_running: bool = True) -> list[dict]:
    with _lock:
        uids = [u for u, st in _states.items()
                if st.get("state") in ("queued", "running", "canceling")]
    return [cancel(u, include_running=include_running) for u in uids]


def _discard_outputs(uid: str) -> None:
    _d, wav, meta = paths(uid)
    for p in (wav, meta):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run, daemon=True, name="vocals")
    _worker.start()


def _run() -> None:
    while True:
        uid, audio = _queue.get()
        with _lock:
            st = _states.get(uid)
            if not st or st.get("state") != "queued":
                _canceled.discard(uid)
                continue
            if uid in _canceled:
                _canceled.discard(uid)
                _states[uid] = {"state": "canceled", "error": "已取消",
                                "since": time.time()}
                continue
            if time.time() - float(st.get("since") or 0) > float(VC["queue_timeout_s"]):
                _states[uid] = {"state": "failed", "error": "人声分离排队超时",
                                "since": time.time()}
                continue
            _states[uid] = {"state": "running", "since": time.time()}
        try:
            m = _separate(uid, audio)
            with _lock:
                if uid in _canceled:
                    _canceled.discard(uid)
                    _states[uid] = {"state": "canceled", "error": "已取消",
                                    "since": time.time()}
                    _discard_outputs(uid)
                else:
                    _states.pop(uid, None)
            m  # 已写盘
        except Cancelled:
            with _lock:
                _canceled.discard(uid)
                _states[uid] = {"state": "canceled", "error": "已取消",
                                "since": time.time()}
            _discard_outputs(uid)
        except Exception as e:                     # 失败保留原因，下次点歌会重试
            with _lock:
                canceled = uid in _canceled
                _canceled.discard(uid)
                _states[uid] = ({"state": "canceled", "error": "已取消",
                                 "since": time.time()} if canceled
                                else {"state": "failed", "error": str(e)[:300],
                                      "since": time.time()})
            if canceled:
                _discard_outputs(uid)


def installed() -> bool:
    try:
        import importlib
        importlib.import_module("demucs")
        return True
    except Exception:
        return bool(shutil.which("demucs"))


def _demucs_cmd() -> list[str]:
    """打包后不能再用 python -m demucs；全量包走 app 子命令，薄壳走外部命令。"""
    diag.log("vocals", f"demucs resolve frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")
    try:
        import importlib
        importlib.import_module("demucs")
        if getattr(sys, "frozen", False):
            return [sys.executable, "--nihonco-demucs"]
    except Exception:
        pass
    found = shutil.which("demucs")
    if found:
        return [found]
    return [sys.executable, "-m", "demucs"]


def _run_process(cmd: list[str], *, timeout: float, env: dict | None = None,
                 timeout_message: str = "人声分离执行超时", uid: str | None = None):
    """在独立进程组运行；超时或取消时杀整组，包含辅助进程。"""
    if _is_canceled(uid):
        raise Cancelled()
    if os.name != "posix":
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(timeout_message)
        if _is_canceled(uid):
            raise Cancelled()
        return r
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env, start_new_session=True)
    if uid:
        with _proc_lock:
            _current[uid] = p
    try:
        if _is_canceled(uid):
            _kill_proc(uid)
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        if _is_canceled(uid):
            raise Cancelled()
        raise RuntimeError(timeout_message)
    except Cancelled:
        raise
    finally:
        if uid:
            with _proc_lock:
                if _current.get(uid) is p:
                    _current.pop(uid, None)
    if _is_canceled(uid):
        raise Cancelled()
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _separate(uid: str, audio: str) -> dict:
    if not installed():
        raise RuntimeError("未安装 demucs（pip install demucs）")
    d, wav, meta_path = paths(uid)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = TMP_ROOT / f"{uid}-{os.getpid()}-{int(time.time() * 1000)}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        cmd = _demucs_cmd() + ["--two-stems=vocals",
                                "-n", MODEL, "-o", str(tmp), audio]
        env = dict(os.environ)
        env.setdefault("HF_ENDPOINT", VC["hf_endpoint"])   # 国内直连 HF 会卡住
        r = _run_process(cmd, env=env, timeout=float(VC["run_timeout_s"]),
                         timeout_message="人声分离执行超时", uid=uid)
        if _is_canceled(uid):
            raise Cancelled()
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "demucs 失败")[-400:])

        src = next(tmp.rglob("vocals.wav"), None) or next(tmp.rglob("vocals.*"), None)
        if not src:
            raise RuntimeError("demucs 没有产出 vocals 文件")

        if _is_canceled(uid):
            raise Cancelled()
        r = _run_process(["ffmpeg", "-y", "-v", "quiet", "-i", str(src),
                          "-ac", "1", "-ar", str(SAMPLE_RATE), str(wav)],
                         timeout=float(VC["run_timeout_s"]),
                         timeout_message="人声分离转码超时", uid=uid)
        if _is_canceled(uid):
            raise Cancelled()
        if r.returncode != 0 or not wav.is_file():
            raise RuntimeError("转 16k 单声道失败")

        if _is_canceled(uid):
            raise Cancelled()
        stats = analyze(wav)
        if _is_canceled(uid):
            raise Cancelled()
        now = int(time.time())
        m = {"model": MODEL, "created": now, "last_used": now,
             "duration": stats["duration"], "ratio": stats["ratio"],
             "floor": stats["floor"], "threshold": stats["threshold"],
             "has_vocals": stats["ratio"] >= MIN_RATIO}
        FS.atomic_write_json(meta_path, m, indent=1)
        if not m["has_vocals"]:
            # 纯音乐不需要 vocals.wav；保留 meta 即可，波形继续用原曲。
            try:
                wav.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        return m
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cleanup(protected=None, max_bytes=None) -> dict:
    """清理 vocals：孤儿、旧 tmp、超出容量时按 last_used 淘汰。"""
    protected = {str(x) for x in (protected or [])}
    max_bytes = int(max_bytes if max_bytes is not None else VC.get("max_bytes", 512 * 1024 * 1024))
    removed_uids: list[str] = []
    freed = 0

    with _lock:
        active = any(st.get("state") in ("queued", "running", "canceling") for st in _states.values())
        active_uids = {u for u, st in _states.items()
                       if st.get("state") in ("queued", "running", "canceling")}
    if TMP_ROOT.is_dir() and not active:
        for p in TMP_ROOT.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

    rows: list[tuple[int, int, str, Path]] = []
    if VOCALS.is_dir():
        for d in list(VOCALS.iterdir()):
            if not d.is_dir() or d.name in active_uids:
                continue
            wav, mp = d / "vocals.wav", d / "meta.json"
            if not mp.is_file():
                shutil.rmtree(d, ignore_errors=True)
                removed_uids.append(d.name)
                continue
            m = FS.read_json(mp, None)
            if not isinstance(m, dict):
                shutil.rmtree(d, ignore_errors=True)
                removed_uids.append(d.name)
                continue
            # 纯音乐可以只有 meta；有人声的缓存必须有 wav。
            if m.get("has_vocals", True) and not wav.is_file():
                shutil.rmtree(d, ignore_errors=True)
                removed_uids.append(d.name)
                continue
            if d.name not in protected:
                size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
                shutil.rmtree(d, ignore_errors=True)
                removed_uids.append(d.name)
                freed += size
                continue
            try:
                used = int(m.get("last_used") or m.get("created") or 0)
            except Exception:
                used = 0
            size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            rows.append((used, size, d.name, d))

    total = sum(x[1] for x in rows)
    for used, size, uid, d in sorted(rows):
        if total <= max_bytes:
            break
        shutil.rmtree(d, ignore_errors=True)
        total -= size
        removed_uids.append(uid)
        freed += size

    diag.log("vocals", f"cleanup removed={len(removed_uids)} freed={freed} total={total}")
    return {"ok": True, "removed": removed_uids, "freed": freed, "total": total}


def analyze(wav_path: Path) -> dict:
    """对 16k 单声道 PCM 做人声活动度统计。"""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    arr = array.array("h")
    arr.frombytes(raw[: len(raw) // 2 * 2])
    frame = max(1, int(sr * FRAME))
    rms: list[float] = []
    for i in range(0, len(arr) - frame + 1, frame):
        s = 0
        for j in range(i, i + frame):
            v = arr[j]
            s += v * v
        rms.append(math.sqrt(s / frame))
    if not rms:
        return {"duration": 0.0, "ratio": 0.0, "floor": 0.0, "threshold": 0.0}
    ordered = sorted(rms)
    floor = ordered[int(len(ordered) * 0.1)]
    threshold = max(floor * VC["floor_mult"], float(VC["abs_threshold"]))
    ratio = sum(1 for x in rms if x > threshold) / len(rms)
    return {"duration": round(len(arr) / sr, 2), "ratio": round(ratio, 3),
            "floor": round(floor, 1), "threshold": round(threshold, 1)}
