#!/usr/bin/env python3
"""纯音测试：SoundTouch / Rubber Band 变速后的音高与谐波。"""
from __future__ import annotations

import json
import math
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "quality-out"
SPEEDS = (0.80, 0.65)
FREQS = (440.0, 220.0, 110.0)
RATE = 44100


def write_tone(path: Path, freq: float, seconds: float = 10.0) -> None:
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    x = 0.3 * np.sin(2 * math.pi * freq * t)
    pcm = np.clip(x * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def pitch_cents(x: np.ndarray, rate: int, expected: float) -> tuple[float, float]:
    # 取中间 3 秒，避开首尾预热。
    if len(x) > 4 * rate:
        x = x[2 * rate:5 * rate]
    x = x - x.mean()
    win = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * win))
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    lo = max(1, np.searchsorted(freqs, 40))
    hi = min(len(spec) - 1, np.searchsorted(freqs, 2000))
    k = lo + int(np.argmax(spec[lo:hi]))
    # 抛物线插值，纯音用 FFT 峰值足够。
    if 0 < k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        den = a - 2 * b + c
        delta = 0.5 * (a - c) / den if den else 0.0
    else:
        delta = 0.0
    f = (k + delta) * rate / len(x)
    cents = 1200 * math.log2(f / expected) if f > 0 else float("inf")
    # 2–6 次谐波能量占比（粗看处理染色）。
    harm = 0.0
    fund = 0.0
    for h in range(1, 7):
        target = expected * h
        idx = np.searchsorted(freqs, target)
        if idx >= len(spec):
            break
        width = max(1, int(5 * len(x) / rate))
        band = spec[max(0, idx - width):idx + width + 1]
        if not len(band):
            continue
        e = float(np.sum(band * band))
        if h == 1:
            fund = e
        else:
            harm += e
    thd = math.sqrt(harm / fund) if fund else float("nan")
    return float(f), cents, thd


def run(cmd: list[str]) -> float:
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-500:]}")
    return dt


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for freq in FREQS:
        src = OUT / f"tone-{int(freq)}.wav"
        write_tone(src, freq)
        for speed in SPEEDS:
            rb = OUT / f"rb-{int(freq)}-{speed:.2f}.wav"
            dt = run(["rubberband", "-3", "-t", f"{1/speed:.8f}", str(src), str(rb)])
            x, rate = read_wav(rb)
            f, cents, thd = pitch_cents(x, rate, freq)
            rows.append({"engine": "Rubber Band R3", "freq": freq, "speed": speed,
                         "out_hz": f, "cents": cents, "thd": thd,
                         "process_s": dt, "duration_s": len(x) / rate})

            st = OUT / f"st-{int(freq)}-{speed:.2f}.wav"
            dt = run(["soundstretch", str(src), str(st), f"-tempo={round((speed-1)*100, 4)}"])
            x, rate = read_wav(st)
            f, cents, thd = pitch_cents(x, rate, freq)
            rows.append({"engine": "SoundTouch", "freq": freq, "speed": speed,
                         "out_hz": f, "cents": cents, "thd": thd,
                         "process_s": dt, "duration_s": len(x) / rate})
    print(f"{'engine':16} {'tone':>5} {'speed':>5} {'out Hz':>10} {'cents':>8} {'THD':>8} {'proc s':>7}")
    for r in rows:
        print(f"{r['engine']:16} {r['freq']:5.0f} {r['speed']:5.2f} {r['out_hz']:10.3f} "
              f"{r['cents']:8.2f} {r['thd']:8.3f} {r['process_s']:7.3f}")
    (ROOT / "quality.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nJSON:", ROOT / "quality.json")


if __name__ == "__main__":
    main()
