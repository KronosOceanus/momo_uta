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

from ..core import diag
from ..core import library as LIB

_CACHE_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_KEY_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_CANCEL_GEN: dict[str, int] = {}
_PENDING: dict[str, int] = {}
_CURRENT = None
_CURRENT_UID = None
CACHE_DIR = CACHE / "soundtouch"
MAX_CACHE_BYTES = 2 * 1024 ** 3
TMP_MAX_AGE = 24 * 3600
RUN_TIMEOUT = 120
CLEANUP_INTERVAL = 5
_LAST_CLEANUP = 0.0


def _executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _tool(name: str, env: str | None = None) -> str | None:
    if env:
        value = os.environ.get(env)
        if value and _executable(Path(value)):
            return value
    if getattr(sys, "frozen", False):
        p = BUNDLE / "bin" / name
        if _executable(p):
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
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                p.kill()
            except OSError:
                pass
        try:
            p.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        pass


def _close_pipes(p) -> None:
    for stream in (p.stdout, p.stderr):
        if stream is not None:
            try:
                stream.close()
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
        idle = not uid or (_PENDING.get(uid, 0) == 0 and _CURRENT_UID != uid)
        if idle and uid:
            _CANCEL_GEN.pop(uid, None)
    _stop(p)
    if p is not None:
        diag.log("soundtouch", f"cancel uid={uid or '-'} speed=cancelled")


def _run(cmd: list[str], uid: str, gen: int) -> None:
    global _CURRENT, _CURRENT_UID
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    deadline = time.monotonic() + RUN_TIMEOUT
    with _STATE_LOCK:
        _CURRENT = p
        _CURRENT_UID = uid
    try:
        while p.poll() is None:
            with _STATE_LOCK:
                canceled = gen != _CANCEL_GEN.get(uid, 0)
            if canceled:
                _stop(p)
                _close_pipes(p)
                raise Cancelled("SoundTouch 生成已取消")
            if time.monotonic() >= deadline:
                _stop(p)
                _close_pipes(p)
                raise TimeoutError(f"SoundTouch 生成超时（>{RUN_TIMEOUT}s）")
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


def cleanup_startup() -> None:
    """启动时清理旧临时目录，并按上限修剪缓存。"""
    global _LAST_CLEANUP
    with _CACHE_LOCK:
        _cleanup()
        _LAST_CLEANUP = time.monotonic()


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate() if w.getframerate() else 0
    except (OSError, wave.Error):
        return 0.0


def _valid_wav(path: Path) -> bool:
    """轻量校验缓存头；不完整/被截断的 WAV 不能复用。"""
    try:
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 2 or w.getframerate() != 44100 or w.getsampwidth() != 2:
                return False
            frames = w.getnframes()
            if frames <= 0:
                return False
            need = frames * w.getnchannels() * w.getsampwidth()
            return path.stat().st_size >= need
    except (OSError, wave.Error):
        return False


def _cache_hit(out: Path) -> bool:
    """在 _CACHE_LOCK 内调用；命中时更新 LRU。"""
    try:
        if not out.is_file():
            return False
        if out.stat().st_size > 44 and _valid_wav(out):
            _touch(out)
            _maybe_cleanup(out)
            return True
        diag.log("soundtouch", f"invalid cache path={out}")
        out.unlink()
    except OSError:
        pass
    return False


def _maybe_cleanup(keep: Path | None = None) -> None:
    """缓存读取不必每次扫 2GB 目录；短时间内的重复命中跳过。"""
    global _LAST_CLEANUP
    now = time.monotonic()
    if now - _LAST_CLEANUP < CLEANUP_INTERVAL:
        return
    _LAST_CLEANUP = now
    _cleanup(keep=keep)


def _key_lock(uid: str, speed: float):
    key = f"{uid}-{speed:.2f}"
    with _STATE_LOCK:
        lock, count = _KEY_LOCKS.get(key, (None, 0))
        if lock is None:
            lock = threading.Lock()
        _KEY_LOCKS[key] = (lock, count + 1)
    lock.acquire()
    return key, lock


def _release_key(key: str, lock: threading.Lock) -> None:
    lock.release()
    with _STATE_LOCK:
        cur = _KEY_LOCKS.get(key)
        if cur and cur[0] is lock:
            count = cur[1] - 1
            if count > 0:
                _KEY_LOCKS[key] = (lock, count)
            else:
                _KEY_LOCKS.pop(key, None)


def cached_path(uid: str, speed: float) -> Path | None:
    """只返回已生成且有效的缓存，不生成。"""
    if not 0.5 <= speed <= 1.25:
        raise ValueError("speed 必须在 0.5–1.25 之间")
    out = _cache_path(str(uid), speed)
    with _CACHE_LOCK:
        if not _cache_hit(out):
            return None
        return out


def process(uid: str, speed: float) -> Path:
    """生成并缓存变速 WAV；重复请求直接复用。"""
    if not 0.5 <= speed <= 1.25:
        raise ValueError("speed 必须在 0.5–1.25 之间")
    item = LIB.resolve(uid)
    if not item or not Path(item["file"]).is_file():
        raise KeyError("歌曲已不可用")
    out = _cache_path(str(uid), speed)
    uid = str(uid)
    with _STATE_LOCK:
        _PENDING[uid] = _PENDING.get(uid, 0) + 1
        gen = _CANCEL_GEN.get(uid, 0)
    started = time.monotonic()
    key = lock = None
    try:
        with _CACHE_LOCK:
            if _cache_hit(out):
                return out
        key, lock = _key_lock(uid, speed)
        with _CACHE_LOCK:
            if gen != _cancel_gen(uid):
                raise Cancelled("SoundTouch 生成已取消")
            if _cache_hit(out):
                return out
        if gen != _cancel_gen(uid):
            raise Cancelled("SoundTouch 生成已取消")
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
            if not _valid_wav(tmp):
                raise RuntimeError("SoundTouch 输出不是有效 WAV")
            # 先完成到临时目录，再短持缓存锁原子搬进缓存。
            with _CACHE_LOCK:
                if gen != _cancel_gen(uid):
                    raise Cancelled("SoundTouch 生成已取消")
                os.replace(tmp, out)
                _touch(out)
                _cleanup(keep=out)
                diag.log("soundtouch",
                         f"generated uid={uid} speed={speed:.2f} bytes={out.stat().st_size} "
                         f"elapsed={time.monotonic()-started:.2f}s")
        return out
    finally:
        if key is not None and lock is not None:
            _release_key(key, lock)
        with _STATE_LOCK:
            n = _PENDING.get(uid, 0) - 1
            if n > 0:
                _PENDING[uid] = n
            else:
                _PENDING.pop(uid, None)
                if _CURRENT_UID != uid:
                    _CANCEL_GEN.pop(uid, None)


def url(uid: str, speed: float) -> str:
    return f"/audio/{uid}?st={speed:.2f}"


def info(uid: str, speed: float) -> dict:
    out = process(uid, speed)
    return {"uid": uid, "speed": speed, "url": url(uid, speed),
            "duration": _duration(out), "bytes": out.stat().st_size}
