"""可重建小缓存的启动清理：wave / annotations / lyrics。

SoundTouch 和 vocals 有各自的容量 LRU；这里只处理没有独立上限的小文件，
避免旧参数、旧注音版本和过期歌词缓存无限堆积。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from momo_yomi.config import CFG
from momo_yomi.paths import CACHE

from . import annotation_cache as ANNO
from . import diag
from . import lyrics_cache as LYC
from . import waveform as WAVE

WAVE_MAX_AGE = 30 * 86400
ANNO_MAX_AGE = 90 * 86400
LYRICS_MAX_AGE = 180 * 86400


def _old(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _unlink(path: Path) -> int:
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def _cleanup_wave(now: float) -> int:
    root = CACHE / "wave"
    if not root.is_dir():
        return 0
    freed = 0
    suffix = f".{WAVE.RATE}.{WAVE.STEP}.json"
    for p in root.glob("*.json"):
        if not p.name.endswith(suffix) or _old(p, now - WAVE_MAX_AGE):
            freed += _unlink(p)
    return freed


def _cleanup_annotations(now: float) -> int:
    root = ANNO.CACHE_DIR
    if not root.is_dir():
        return 0
    freed = 0
    for p in root.glob("*.json"):
        remove = _old(p, now - ANNO_MAX_AGE)
        if not remove:
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                remove = not isinstance(obj, dict) or obj.get("v") != ANNO.VERSION
            except Exception:
                remove = True
        if remove:
            freed += _unlink(p)
    return freed


def _cleanup_lyrics(now: float) -> int:
    root = LYC.CACHE
    if not root.is_dir():
        return 0
    neg_ttl = float(CFG.get("negative_ttl_days", 7) or 0) * 86400
    freed = 0
    for p in root.glob("*.json"):
        remove = False
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict) and obj.get("miss"):
                checked = float(obj.get("checked_at") or p.stat().st_mtime)
                remove = neg_ttl <= 0 or now - checked >= neg_ttl
            else:
                remove = _old(p, now - LYRICS_MAX_AGE)
        except Exception:
            remove = True
        if remove:
            freed += _unlink(p)
    return freed


def cleanup_startup() -> dict:
    """启动时清理旧小缓存；失败不影响启动。"""
    now = time.time()
    out = {"wave": 0, "annotations": 0, "lyrics": 0}
    try:
        out["wave"] = _cleanup_wave(now)
    except Exception as e:
        diag.log("cache", f"wave cleanup failed: {e}")
    try:
        out["annotations"] = _cleanup_annotations(now)
    except Exception as e:
        diag.log("cache", f"annotations cleanup failed: {e}")
    try:
        out["lyrics"] = _cleanup_lyrics(now)
    except Exception as e:
        diag.log("cache", f"lyrics cleanup failed: {e}")
    if any(out.values()):
        diag.log("cache", "cleanup " + " ".join(f"{k}={v}" for k, v in out.items()))
    return out
