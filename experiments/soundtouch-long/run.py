#!/usr/bin/env python3
"""长歌曲 SoundTouch 生成性能测试（不提交生成物）。"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from momo_player.service import soundtouch as ST

ROOT = Path(__file__).resolve().parent
SRC = Path.home() / "Music" / "网易云音乐" / "YOASOBI - たぶん.mp3"
RATE = 44100


def make_source(path: Path, seconds: float) -> None:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-stream_loop", "-1", "-i", str(SRC), "-t", str(seconds),
        "-c:a", "libmp3lame", "-b:a", "192k", str(path),
    ], check=True)


def run_one(uid: str, path: Path, speed: float) -> dict:
    item = {"uid": uid, "file": str(path)}
    old = ST.LIB.resolve
    ST.LIB.resolve = lambda _uid: item
    try:
        t0 = time.perf_counter()
        out = ST.process(uid, speed)
        elapsed = time.perf_counter() - t0
        size = out.stat().st_size
        # 输出时长由 WAV 头/大小估算；这里用 ST._duration。
        dur = ST._duration(out)
        t0 = time.perf_counter()
        ST.process(uid, speed)
        hot = time.perf_counter() - t0
        return {
            "uid": uid,
            "source_s": None,
            "speed": speed,
            "elapsed_s": elapsed,
            "out_s": dur,
            "bytes": size,
            "audio_buffer_mb": dur * RATE * 2 * 4 / 1e6,
            "hot_s": hot,
        }
    finally:
        ST.LIB.resolve = old


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"找不到测试音频：{SRC}")
    rows = []
    with tempfile.TemporaryDirectory(prefix="momo-long-", dir="/tmp") as td, \
         tempfile.TemporaryDirectory(prefix="momo-st-cache-", dir="/tmp") as cd:
        td = Path(td)
        ST.CACHE = Path(cd)
        ST.CACHE_DIR = ST.CACHE / "soundtouch"
        cases = []
        for label, seconds in (("4min", 258), ("8min", 480), ("10min", 600)):
            src = td / f"{label}.mp3"
            make_source(src, seconds)
            cases.append((label, seconds, src))
        for label, seconds, src in cases:
            for speed in (0.65, 1.25):
                uid = f"long-{label}-{speed}"
                try:
                    r = run_one(uid, src, speed)
                    r["source_s"] = seconds
                    rows.append(r)
                    print(json.dumps(r, ensure_ascii=False))
                except Exception as e:
                    import traceback
                    print(f"{label} {speed}: ERROR {e}")
                    traceback.print_exc()
        # 真实取消：10 分钟 0.50×，启动后立即取消。
        src = cases[-1][2]
        uid = "long-cancel-050"
        item = {"uid": uid, "file": str(src)}
        old = ST.LIB.resolve
        ST.LIB.resolve = lambda _uid: item
        result = {}
        def worker():
            try:
                ST.process(uid, 0.50)
                result["state"] = "finished"
            except ST.Cancelled:
                result["state"] = "cancelled"
            except Exception as e:
                result["state"] = f"error: {e}"
        try:
            t = threading.Thread(target=worker)
            t.start()
            deadline = time.time() + 3
            while ST._CURRENT is None and time.time() < deadline:
                time.sleep(0.005)
            time.sleep(0.05)
            t0 = time.perf_counter()
            ST.cancel(uid)
            t.join(5)
            result["cancel_s"] = time.perf_counter() - t0
            result["thread_alive"] = t.is_alive()
            print("cancel", json.dumps(result, ensure_ascii=False))
        finally:
            ST.LIB.resolve = old
    (ROOT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("rows", len(rows))


if __name__ == "__main__":
    main()
