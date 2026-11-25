#!/usr/bin/env python3
"""长片段离线吞吐测试：SoundTouch vs Rubber Band。"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "throughput-out"


def run(cmd: list[str]) -> float:
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-1000:]}")
    return dt


def info(path: Path) -> tuple[float, int]:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate(), w.getframerate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--speeds", nargs="+", type=float, default=[0.8, 0.65])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(args.input).expanduser()
    if not src.is_file():
        raise SystemExit(f"找不到 {src}")
    original = OUT / "original.wav"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-t", str(args.seconds), "-i", str(src),
         "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(original)])
    orig_dur, _ = info(original)
    rows = []
    for speed in args.speeds:
        rb = OUT / f"rubberband-{speed:.2f}.wav"
        dt = run(["rubberband", "-3", "-t", f"{1/speed:.8f}", str(original), str(rb)])
        dur, _ = info(rb)
        rows.append({"engine": "Rubber Band R3", "speed": speed, "duration": dur,
                     "process_s": dt, "realtime": dur / dt})

        st = OUT / f"soundtouch-{speed:.2f}.wav"
        dt = run(["soundstretch", str(original), str(st),
                  f"-tempo={round((speed - 1) * 100, 4)}"])
        dur, _ = info(st)
        rows.append({"engine": "SoundTouch", "speed": speed, "duration": dur,
                     "process_s": dt, "realtime": dur / dt})
    print(f"original {orig_dur:.2f}s")
    print(f"{'engine':16} {'speed':>5} {'out s':>8} {'proc s':>8} {'realtime':>9}")
    for r in rows:
        print(f"{r['engine']:16} {r['speed']:5.2f} {r['duration']:8.2f} "
              f"{r['process_s']:8.3f} {r['realtime']:8.1f}x")
    (ROOT / "throughput.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("JSON:", ROOT / "throughput.json")


if __name__ == "__main__":
    main()
