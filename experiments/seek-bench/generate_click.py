#!/usr/bin/env python3
"""生成 12 秒 click track：每 0.5 秒一个 2ms 的 2kHz 短脉冲。"""
from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path

RATE = 44100
DURATION = 12.0
INTERVAL = 0.5
CLICK_SEC = 0.002


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).with_name("click.wav")))
    args = ap.parse_args()
    n = int(RATE * DURATION)
    samples = [0.0] * n
    click_n = int(RATE * CLICK_SEC)
    pos = 0.0
    while pos < DURATION:
        start = int(pos * RATE)
        for i in range(click_n):
            if start + i >= n:
                break
            env = math.sin(math.pi * i / click_n) ** 2
            samples[start + i] += 0.8 * env * math.sin(2 * math.pi * 2000 * i / RATE)
        pos += INTERVAL
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    print(args.out)


if __name__ == "__main__":
    main()
