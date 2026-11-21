#!/usr/bin/env python3
"""波形峰值：ffmpeg 解码成 8kHz 单声道，按 20ms 取 min/max，结果缓存。

一次生成后可反复读；不联网，也不改动原始音频。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from nihonco_yomi.config import WV
from nihonco_yomi.paths import CACHE

from . import fsio as FS

WAVE_DIR = CACHE / "wave"
STEP = WV["step"]    # 峰值步长（秒）
RATE = WV["rate"]    # 解码采样率


def _key(path: str) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()[:16]


def cache_path(audio: str, source: str = "mix") -> Path:
    # 把 rate/step 并进键：改了参数旧缓存自动失效
    return WAVE_DIR / f"{_key(audio)}.{source}.{RATE}.{STEP}.json"


def peaks(audio: str, source: str = "mix", force: bool = False) -> dict:
    """返回 {duration, step, peaks:[[min,max],...]}；失败返回 {"error": ...}。"""
    p = cache_path(audio, source)
    if p.exists() and not force:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass

    wav = Path(audio)
    if not wav.is_file():
        return {"error": "音频文件不存在"}

    per = int(RATE * STEP)
    peaks: list[list[int]] = []
    cur_min, cur_max, cur_n = 0, 0, 0
    total = 0
    try:
        proc = subprocess.Popen(
            ["ffmpeg", "-v", "quiet", "-i", str(wav), "-ac", "1",
             "-ar", str(RATE), "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return {"error": "没有 ffmpeg"}

    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(per * 2 * 200)      # 一次读 200 个桶
        if not chunk:
            break
        n = len(chunk) // 2
        for i in range(n):
            v = int.from_bytes(chunk[2 * i:2 * i + 2], "little", signed=True)
            cur_min = min(cur_min, v) if cur_n else v
            cur_max = max(cur_max, v) if cur_n else v
            cur_n += 1
            total += 1
            if cur_n == per:
                peaks.append([cur_min / 32768.0, cur_max / 32768.0])
                cur_min, cur_max, cur_n = 0, 0, 0
    proc.wait()
    if cur_n:                                        # 尾巴
        peaks.append([cur_min / 32768.0, cur_max / 32768.0])

    out = {"duration": round(total / RATE, 2), "step": STEP,
           "peaks": [[round(a, 4), round(b, 4)] for a, b in peaks]}
    FS.atomic_write_json(p, out, indent=None)
    return out
