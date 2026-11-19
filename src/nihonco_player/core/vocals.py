#!/usr/bin/env python3
"""人声分离：demucs 两轨模式跑一次，缓存 16k 单声道人声 + 元数据。

只做三件事：
  1. 队列化调用 demucs（串行，一条一条跑）
  2. 把 vocals.wav 转成 16k 单声道（波形与判定只用它）
  3. 算"有没有人声"的指标，写进 meta.json
"""
from __future__ import annotations

import array
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from queue import Queue

from nihonco_yomi.config import VC
from nihonco_yomi.paths import VOCALS

MODEL = VC["model"]
MIN_RATIO = VC["ratio_min"]          # 有唱帧占比超过它 → 认为有人声
FRAME = VC["frame_sec"]              # VAD 帧长（秒）
SAMPLE_RATE = VC["sample_rate"]

_queue: Queue = Queue()
_states: dict[str, dict] = {}
_lock = threading.Lock()
_worker: threading.Thread | None = None


def paths(uid: str) -> tuple[Path, Path, Path]:
    d = VOCALS / uid
    return d, d / "vocals.wav", d / "meta.json"


def meta(uid: str) -> dict | None:
    _, _, m = paths(uid)
    try:
        return json.loads(m.read_text(encoding="utf-8"))
    except Exception:
        return None


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
        return status(uid)
    with _lock:
        st = _states.get(uid)
        if st and st.get("state") in ("queued", "running"):
            return dict(st)
        _states[uid] = {"state": "queued", "since": time.time()}
        _queue.put((uid, str(audio)))
        _start_worker()
        return dict(_states[uid])


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
            _states[uid] = {"state": "running", "since": time.time()}
        try:
            m = _separate(uid, audio)
            with _lock:
                _states.pop(uid, None)
            m  # 已写盘
        except Exception as e:                     # 失败保留原因，下次点歌会重试
            with _lock:
                _states[uid] = {"state": "failed", "error": str(e)[:300],
                                "since": time.time()}


def installed() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except Exception:
        return False


def _separate(uid: str, audio: str) -> dict:
    if not installed():
        raise RuntimeError("未安装 demucs（pip install demucs）")
    d, wav, meta_path = paths(uid)
    tmp = d / "tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals",
           "-n", MODEL, "-o", str(tmp), audio]
    env = dict(os.environ)
    env.setdefault("HF_ENDPOINT", VC["hf_endpoint"])   # 国内直连 HF 会卡住
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "demucs 失败")[-400:])

    src = next(tmp.rglob("vocals.wav"), None) or next(tmp.rglob("vocals.*"), None)
    if not src:
        raise RuntimeError("demucs 没有产出 vocals 文件")

    r = subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-i", str(src),
                        "-ac", "1", "-ar", str(SAMPLE_RATE), str(wav)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not wav.is_file():
        raise RuntimeError("转 16k 单声道失败")

    stats = analyze(wav)
    m = {"model": MODEL, "created": int(time.time()),
         "duration": stats["duration"], "ratio": stats["ratio"],
         "floor": stats["floor"], "threshold": stats["threshold"],
         "has_vocals": stats["ratio"] >= MIN_RATIO}
    meta_path.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    return m


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
