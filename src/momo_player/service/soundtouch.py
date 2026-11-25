"""最小 SoundTouch 原调试听：把当前歌曲预生成一份变速 WAV。

只用于试听，不改变正式播放引擎；输出时间轴和原波形/歌词不一致。
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from momo_yomi.paths import BUNDLE, CACHE

from ..core import library as LIB

LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_CANCEL_GEN: dict[str, int] = {}
_CURRENT = None
_CURRENT_UID = None
CACHE_DIR = CACHE / "soundtouch"
MAX_CACHE_BYTES = 2 * 1024 ** 3
TMP_MAX_AGE = 24 * 3600


def _tool(name: str, env: str | None = None) -> str | None:
    if env:
        value = os.environ.get(env)
        if value and Path(value).is_file():
            return value
    if getattr(sys, "frozen", False):
        p = BUNDLE / "bin" / name
        if p.is_file():
            return str(p)
    return shutil.which(name)


class Cancelled(RuntimeError):
    pass


def _stop(p) -> None:
    if p is None:
        return
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            p.terminate()
        except OSError:
            pass


def _cancel_gen(uid: str) -> int:
    with _STATE_LOCK:
        return _CANCEL_GEN.get(uid, 0)


def cancel(uid: str | None = None) -> None:
    """取消指定歌曲当前/排队中的生成；不传 uid 时取消当前进程。"""
    global _CURRENT
    uid = str(uid or "")
    with _STATE_LOCK:
        if uid:
            _CANCEL_GEN[uid] = _CANCEL_GEN.get(uid, 0) + 1
        p = _CURRENT if (not uid or _CURRENT_UID == uid) else None
    _stop(p)


def _run(cmd: list[str], uid: str, gen: int) -> None:
    global _CURRENT, _CURRENT_UID
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    with _STATE_LOCK:
        _CURRENT = p
        _CURRENT_UID = uid
    try:
        while p.poll() is None:
            with _STATE_LOCK:
                canceled = gen != _CANCEL_GEN.get(uid, 0)
            if canceled:
                _stop(p)
                raise Cancelled("SoundTouch 生成已取消")
            time.sleep(0.05)
        out, err = p.communicate()
        if gen != _cancel_gen(uid):
            raise Cancelled("SoundTouch 生成已取消")
        if p.returncode != 0:
            raise RuntimeError((err or out or "SoundTouch 生成失败")[-500:])
    finally:
        with _STATE_LOCK:
            if _CURRENT is p:
                _CURRENT = None
                _CURRENT_UID = None


def _cache_path(uid: str, speed: float) -> Path:
    return CACHE_DIR / f"{uid}-{speed:.2f}.wav"


def _touch(path: Path) -> None:
    try:
        os.utime(path, None)
    except OSError:
        pass


def _cleanup(keep: Path | None = None) -> None:
    """按 mtime 做 LRU；同时清掉崩溃遗留的生成临时目录。"""
    files = []
    try:
        files = [p for p in CACHE_DIR.glob("*.wav") if p.is_file()]
    except OSError:
        pass
    total = 0
    entries = []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        total += st.st_size
        entries.append((st.st_mtime, st.st_size, p))
    entries.sort()
    for _mtime, size, p in entries:
        if total <= MAX_CACHE_BYTES:
            break
        if keep is not None and p == keep:
            continue
        try:
            p.unlink()
            total -= size
        except OSError:
            pass
    # TemporaryDirectory 正常会自删；这里只处理异常退出留下的旧目录。
    try:
        cutoff = time.time() - TMP_MAX_AGE
        for d in CACHE.glob("momo-st-*"):
            if d.is_dir():
                try:
                    if d.stat().st_mtime < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


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
    uid = str(uid)
    gen = _cancel_gen(uid)
    with LOCK:
        if gen != _cancel_gen(uid):
            raise Cancelled("SoundTouch 生成已取消")
        if out.is_file() and out.stat().st_size > 44:
            _touch(out)
            _cleanup(keep=out)
            return out
        ffmpeg = _tool("ffmpeg", "MOMO_FFMPEG")
        soundstretch = _tool("soundstretch", "MOMO_SOUNDSTRETCH")
        if not ffmpeg or not soundstretch:
            raise RuntimeError("试听需要 ffmpeg 和 soundstretch（brew install ffmpeg sound-touch）")
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="momo-st-", dir=str(CACHE)) as td:
            src = Path(td) / "src.wav"
            tmp = Path(td) / "out.wav"
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                  "-i", str(item["file"]), "-ac", "2", "-ar", "44100",
                  "-c:a", "pcm_s16le", str(src)], uid, gen)
            _run([soundstretch, str(src), str(tmp),
                  f"-tempo={round((speed - 1) * 100, 4)}"], uid, gen)
            if gen != _cancel_gen(uid):
                raise Cancelled("SoundTouch 生成已取消")
            # 先完成到临时目录，再原子搬进缓存。
            os.replace(tmp, out)
            _touch(out)
            _cleanup(keep=out)
        return out


def url(uid: str, speed: float) -> str:
    return f"/audio/{uid}?st={speed:.2f}"


def info(uid: str, speed: float) -> dict:
    out = process(uid, speed)
    return {"uid": uid, "speed": speed, "url": url(uid, speed),
            "duration": _duration(out), "bytes": out.stat().st_size}
