#!/usr/bin/env python3
"""SoundTouch vs Rubber Band 独立听感/速度实验。

只依赖 ffmpeg、soundstretch、rubberband，不接入播放器。

用法：
  .venv/bin/python experiments/time-stretch/run.py \
    --input "$HOME/Music/网易云音乐/YOASOBI - たぶん.mp3" \
    --start 30 --seconds 20 --speeds 0.8 0.65
"""
from __future__ import annotations

import argparse
import html
import json
import os
import resource
import shutil
import subprocess
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


def run(cmd: list[str], label: str) -> dict:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if p.returncode:
        raise SystemExit(f"{label} 失败（{p.returncode}）\n{p.stderr[-2000:]}")
    return {
        "elapsed": elapsed,
        "cpu": (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime),
    }


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        width = w.getsampwidth()
        channels = w.getnchannels()
    return {
        "duration": frames / rate if rate else 0,
        "rate": rate,
        "channels": channels,
        "width": width,
        "bytes": path.stat().st_size,
    }


def make_excerpt(src: Path, start: float, seconds: float) -> Path:
    dst = OUT / "original.wav"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(start), "-t", str(seconds), "-i", str(src),
           "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)]
    run(cmd, "ffmpeg")
    return dst


def stretch(src: Path, speed: float) -> list[dict]:
    rows = []
    # rubberband -t 是时间倍率；0.8 倍速 = 1/0.8 倍时长。
    rb_out = OUT / f"rubberband-{speed:.2f}.wav"
    rb = run(["rubberband", "-3", "-t", f"{1 / speed:.8f}",
              str(src), str(rb_out)], "rubberband")
    rows.append({"engine": "Rubber Band R3", "speed": speed,
                 "file": rb_out, **rb, **wav_info(rb_out)})

    # SoundTouch -tempo 是百分比：0.8 倍速 = -20%。
    st_out = OUT / f"soundtouch-{speed:.2f}.wav"
    tempo = round((speed - 1) * 100, 4)
    st = run(["soundstretch", str(src), str(st_out), f"-tempo={tempo}"],
             "soundstretch")
    rows.append({"engine": "SoundTouch", "speed": speed,
                 "file": st_out, **st, **wav_info(st_out)})
    return rows


def report(rows: list[dict], original: dict, src: Path, start: float) -> None:
    def href(p: Path) -> str:
        return html.escape(p.relative_to(ROOT).as_posix())

    table = []
    for row in rows:
        table.append(
            "<tr>"
            f"<td>{html.escape(row['engine'])}</td>"
            f"<td>{row['speed']:.2f}×</td>"
            f"<td>{row['duration']:.3f}s</td>"
            f"<td>{row['elapsed']:.3f}s</td>"
            f"<td>{row['duration'] / row['elapsed']:.2f}×</td>"
            f"<td>{row['cpu']:.3f}s</td>"
            "</tr>")

    players = [
        f"<h2>原始片段</h2><audio controls src=\"{href(OUT / 'original.wav')}\"></audio>"
    ]
    for row in rows:
        players.append(
            f"<h2>{html.escape(row['engine'])} · {row['speed']:.2f}×</h2>"
            f"<audio controls src=\"{href(row['file'])}\"></audio>")

    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>SoundTouch vs Rubber Band</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:980px;
margin:40px auto;padding:0 20px;line-height:1.5;color:#222}}
h1{{margin-bottom:4px}} .muted{{color:#777}}
audio{{width:100%;max-width:620px;margin:8px 0 20px}}
table{{border-collapse:collapse;width:100%;margin:18px 0}}
th,td{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}
th{{background:#f6f6f6}} code{{background:#f2f2f2;padding:2px 5px;border-radius:4px}}
</style>
<h1>SoundTouch vs Rubber Band</h1>
<p class="muted">源文件：<code>{html.escape(str(src))}</code> · 起点 {start:.1f}s · 原始片段 {original['duration']:.2f}s</p>
<p>同一段音频、同一速度。请用同一音量切换试听，比较人声、鼓点、贝斯和瞬态。</p>
<table>
<tr><th>引擎</th><th>速度</th><th>输出时长</th><th>处理耗时</th><th>实时倍率</th><th>CPU</th></tr>
{''.join(table)}
</table>
<p class="muted">实时倍率 = 输出音频时长 / 实际处理耗时，越大越快。CPU 为子进程用户+系统时间。</p>
<h2>原始片段</h2><audio controls src="{href(OUT / 'original.wav')}"></audio>
{''.join(p for p in players[1:])}
<hr>
<p class="muted">本实验是离线处理，不测实时 seek。seek 需要接播放引擎后单独测。</p>
"""
    (ROOT / "report.html").write_text(doc, encoding="utf-8")
    (ROOT / "metrics.json").write_text(
        json.dumps({"source": str(src), "start": start,
                    "original": original, "results": [
                        {k: (str(v) if isinstance(v, Path) else v)
                         for k, v in row.items()} for row in rows]},
                   ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="输入音频")
    ap.add_argument("--start", type=float, default=30, help="片段起点秒")
    ap.add_argument("--seconds", type=float, default=20, help="片段长度秒")
    ap.add_argument("--speeds", nargs="+", type=float, default=[0.8, 0.65])
    args = ap.parse_args()
    src = Path(args.input).expanduser()
    if not src.is_file():
        raise SystemExit(f"找不到输入：{src}")
    if not shutil.which("ffmpeg") or not shutil.which("rubberband") or not shutil.which("soundstretch"):
        raise SystemExit("需要 ffmpeg、rubberband、soundstretch 都在 PATH")
    OUT.mkdir(parents=True, exist_ok=True)
    original_path = make_excerpt(src, args.start, args.seconds)
    original = wav_info(original_path)
    rows = []
    for speed in args.speeds:
        if not 0.5 <= speed <= 1.0:
            raise SystemExit("这个实验只比较 0.5–1.0 倍速")
        rows.extend(stretch(original_path, speed))
    report(rows, original, src, args.start)
    print(f"报告：{ROOT / 'report.html'}")
    print(f"数据：{ROOT / 'metrics.json'}")


if __name__ == "__main__":
    main()
