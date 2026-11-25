"""最小 SoundTouch 原调试听：把当前歌曲预生成一份变速 WAV。

只用于试听，不改变正式播放引擎；输出时间轴和原波形/歌词不一致。
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from momo_yomi.paths import CACHE

from ..core import library as LIB

LOCK = threading.Lock()


def _cache_path(uid: str, speed: float) -> Path:
    return CACHE / "soundtouch" / f"{uid}-{speed:.2f}.wav"


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate() if w.getframerate() else 0
    except (OSError, wave.Error):
        return 0.0


def process(uid: str, speed: float) -> Path:
    """生成并缓存变速 WAV；重复请求直接复用。"""
    if not 0.5 <= speed <= 1.25:
        raise ValueError("speed 必须在 0.5–1.25 之间")
    item = LIB.resolve(uid)
    if not item or not Path(item["file"]).is_file():
        raise KeyError("歌曲已不可用")
    out = _cache_path(str(uid), speed)
    with LOCK:
        if out.is_file() and out.stat().st_size > 44:
            return out
        ffmpeg = shutil.which("ffmpeg")
        soundstretch = shutil.which("soundstretch")
        if not ffmpeg or not soundstretch:
            raise RuntimeError("试听需要 ffmpeg 和 soundstretch（brew install ffmpeg sound-touch）")
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="momo-st-", dir=str(CACHE)) as td:
            src = Path(td) / "src.wav"
            tmp = Path(td) / "out.wav"
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(item["file"]), "-ac", "2", "-ar", "44100",
                            "-c:a", "pcm_s16le", str(src)], check=True, timeout=120)
            subprocess.run([soundstretch, str(src), str(tmp),
                            f"-tempo={round((speed - 1) * 100, 4)}"],
                           check=True, timeout=120)
            # 先完成到临时目录，再原子搬进缓存。
            import os
            os.replace(tmp, out)
        return out


def url(uid: str, speed: float) -> str:
    return f"/audio/{uid}?st={speed:.2f}"


def info(uid: str, speed: float) -> dict:
    out = process(uid, speed)
    return {"uid": uid, "speed": speed, "url": url(uid, speed),
            "duration": _duration(out), "bytes": out.stat().st_size}
