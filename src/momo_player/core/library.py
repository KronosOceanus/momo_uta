#!/usr/bin/env python3
"""歌曲库：扫目录、读缓存、人工标签。只有文件和缓存，没有 HTTP。"""
from __future__ import annotations

import hashlib
import os
import threading
import json
import time
from pathlib import Path

from momo_yomi.config import LB
from momo_yomi.paths import ROOT

from . import diag
from . import fingerprint as FP
from . import fsio as FS
from . import library_index as LI
from . import lrc_files as LRC
from . import playlists as PL
from . import lyrics as LY

MUSIC = Path.home() / "Music" / "网易云音乐"
IMPORTS = ROOT / "data" / "curated" / "imports.json"     # 导入的音频路径（不在 music_dirs 里也能列）
CACHE: dict = {}          # idx(str) -> 歌曲条目（列表顺序）
BY_UID: dict = {}         # uid -> 歌曲条目（唯一歌曲身份）
LAST_MISSING: list[str] = []   # 最近一次加载未解析到的歌单 uid

def music_dirs() -> list[Path]:
    from momo_yomi.config import PL
    dirs = PL.get("music_dirs") or [str(MUSIC)]
    return [Path(str(d)).expanduser() for d in dirs]


def roots_available() -> bool:
    """音乐根目录存在且可读时，才允许把缺失路径当成永久删除。"""
    roots = music_dirs()
    if not roots:
        return False
    try:
        return all(p.is_dir() and os.access(p, os.R_OK) for p in roots)
    except OSError:
        return False


def load_imports() -> list[dict]:
    """读导入历史；坏行丢弃，不因为一行坏数据丢掉全部。"""
    try:
        raw = json.loads(IMPORTS.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        audio = row.get("audio")
        if not isinstance(audio, str) or not audio:
            continue
        if audio in seen:
            continue
        seen.add(audio)
        out.append({
            "audio": audio,
            "title": row.get("title") if isinstance(row.get("title"), str) else "",
            "artist": row.get("artist") if isinstance(row.get("artist"), str) else "",
        })
    return out


def save_import(audio: str, title: str, artist: str) -> None:
    lock = IMPORTS.with_suffix(".lock")
    with FS.locked(lock):
        rows = load_imports()
        if any(r.get("audio") == audio for r in rows):
            return
        rows.append({"audio": audio, "title": title, "artist": artist})
        FS.atomic_write_json(IMPORTS, rows, indent=1)


_LOCK = threading.RLock()


def _publish(entries: list[dict]) -> None:
    """一次性发布新曲库：不先清空 CACHE，uid 索引同步更新。"""
    new = {str(i): e for i, e in enumerate(entries)}
    by_uid = {str(e["uid"]): e for e in entries if e.get("uid")}
    with _LOCK:
        old = set(CACHE)
        CACHE.update(new)
        for k in old - set(new):
            CACHE.pop(k, None)
        BY_UID.clear()
        BY_UID.update(by_uid)


def resolve(uid) -> dict | None:
    """只按 uid 找歌；idx 不再是身份。"""
    if uid is None:
        return None
    with _LOCK:
        return BY_UID.get(str(uid))


def idx_for(uid) -> str | None:
    """uid → 当前列表 idx，仅用于展示。"""
    if uid is None:
        return None
    uid = str(uid)
    with _LOCK:
        target = BY_UID.get(uid)
        if target is not None:
            for k, v in CACHE.items():
                if v is target:
                    return k
        for k, v in CACHE.items():
            if str(v.get("uid")) == uid:
                return k
    return None


def snapshot() -> list[tuple[str, dict]]:
    with _LOCK:
        return list(CACHE.items())


def _resolve_uid(uid: str) -> tuple[Path, str] | None:
    """按已有索引/imports 找 uid；找不到返回 None，绝不扫全库。"""
    paths = []
    for p in (FP.paths_for_uids([uid]).get(uid) or []) + (LI.paths_by_uid().get(uid) or []):
        paths.append(Path(p))
    for row in load_imports():
        if row.get("audio"):
            paths.append(Path(str(row["audio"])).expanduser())
    seen = set()
    for p in paths:
        if str(p) in seen or not p.is_file():
            continue
        seen.add(str(p))
        e = _entry(p, "导入" if p in [Path(str(r.get("audio") or "")).expanduser()
                                     for r in load_imports() if r.get("audio")] else (p.parent.name or "曲库"))
        if e and str(e["uid"]) == str(uid):
            return p, e.get("group", "")
    return None


def refresh(uid: str | None = None) -> int:
    """重建 CACHE。uid 不在 CACHE 时只尝试已有索引，不扫全库。"""
    global LAST_MISSING
    with _LOCK:
        lost: set[str] = set()
        if uid is not None:
            stored = LRC.store_index({str(uid)})
            for k, v in list(CACHE.items()):
                if str(v.get("uid")) == str(uid):
                    e = _entry(Path(v["file"]), v.get("group", ""), stored=stored, force_fp=True)
                    old_uid = str(v.get("uid") or "")
                    if e:
                        new_uid = str(e["uid"])
                        CACHE[k] = e
                        if old_uid:
                            BY_UID.pop(old_uid, None)
                            remaining = _live_copy(old_uid, exclude=v["file"])
                            if remaining:
                                BY_UID[old_uid] = remaining
                            elif old_uid != new_uid:
                                lost.add(old_uid)
                        BY_UID[new_uid] = e
                    else:
                        # 文件已经不在：删掉内存条目，避免库列表显示幽灵歌。
                        CACHE.pop(k, None)
                        if old_uid:
                            BY_UID.pop(old_uid, None)
                            remaining = _live_copy(old_uid, exclude=v["file"])
                            if remaining:
                                BY_UID[old_uid] = remaining
                            else:
                                lost.add(old_uid)
                        LI.prune_paths([v["file"]])
                        FP.prune_paths([v["file"]])
                    if lost:
                        LAST_MISSING = sorted(set(LAST_MISSING) | lost)
                    LI.flush()
                    FP.flush()
                    return len(CACHE)
            found = _resolve_uid(str(uid))
            if found:
                p, group = found
                e = _entry(p, group, stored=stored, force_fp=True)
                if e:
                    nums = [int(k) for k in CACHE if str(k).isdigit()]
                    CACHE[str(max(nums) + 1 if nums else 0)] = e
                    old_uid = str(uid)
                    new_uid = str(e["uid"])
                    BY_UID.pop(old_uid, None)
                    remaining = _live_copy(old_uid, exclude=str(p))
                    if remaining:
                        BY_UID[old_uid] = remaining
                    elif old_uid != new_uid:
                        lost.add(old_uid)
                    BY_UID[new_uid] = e
                else:
                    lost.add(str(uid))
                    LI.prune_paths([str(p)])
                    FP.prune_paths([str(p)])
            if lost:
                LAST_MISSING = sorted(set(LAST_MISSING) | lost)
            LI.flush()
            return len(CACHE)
        lib = scan_library()
        _publish(lib)
        return len(CACHE)


def add_paths(paths, group: str = "导入") -> list[dict]:
    """只把指定文件加进 CACHE，不动已有 idx，也不扫全库。"""
    out: list[dict] = []
    with _LOCK:
        seen = {v["file"] for v in CACHE.values()}
        nums = [int(k) for k in CACHE if str(k).isdigit()]
        nxt = max(nums) + 1 if nums else 0
        for raw in paths:
            p = Path(str(raw)).expanduser()
            if p.suffix.lower() not in tuple(LB["extensions"]) or not p.is_file():
                continue
            if str(p) in seen:
                continue
            e = _entry(p, group)
            if not e or e["file"] in seen:
                continue
            CACHE[str(nxt)] = e
            BY_UID[str(e["uid"])] = e
            nxt += 1
            seen.add(e["file"])
            out.append(e)
    LI.flush()
    FP.flush()
    return out


def _has_lyric(title: str, artist: str, uid=None, stored=None) -> bool:
    if uid is not None and stored is not None and str(uid) in stored:
        return bool(stored[str(uid)])
    if not LY._cached(title, artist):
        return False
    hit = LY.get_lrc(title, artist, use_cache=True, network=False) or {}
    lrc = hit.get("lrc") or ""
    return (LY.content_lines(lrc) >= int(LY.CFG["min_content_lines"]) and LY.has_timed(lrc))


def _live_copy(uid: str, exclude: str | None = None) -> dict | None:
    """找出仍然真实持有 uid 的副本；必须验证文件存在且指纹匹配。"""
    for x in list(CACHE.values()):
        if str(x.get("uid")) != str(uid):
            continue
        f = str(x.get("file") or "")
        if not f or (exclude and f == exclude):
            continue
        p = Path(f)
        if not p.is_file():
            continue
        e = _entry(p, x.get("group", ""), force_fp=True)
        if e and str(e.get("uid")) == str(uid):
            return e
    return None


def _entry(p: Path, group: str, stored=None, force_fp: bool = False) -> dict | None:
    stem = p.stem
    # 不再按"像不像日文歌"过滤：进了歌单就应该看得见。
    # 过滤只用于歌词匹配时的判断（is_likely_song 仍被匹配流程使用）。
    rec = LI.get(p)
    forced_uid = FP.fingerprint(p, force=True) if force_fp else None
    if forced_uid and rec and str(rec.get("uid")) != forced_uid:
        rec = None
    if rec:
        rec_artist, rec_title = LY.split_name(rec.get("stem") or stem)
        return {"key": rec.get("key") or hashlib.md5(stem.encode()).hexdigest()[:12],
                "uid": rec["uid"], "file": str(p), "stem": rec.get("stem") or stem,
                "orig": rec.get("orig") or rec.get("title") or stem,
                "group": group or rec.get("group", ""),
                "title": rec.get("title") or stem,
                "artist": rec.get("artist", ""),
                "source": rec.get("source", ""),
                "lang": rec.get("lang") or "unknown",
                "has_lyric": _has_lyric(rec_title, rec_artist,
                                        uid=rec["uid"], stored=stored),
                "suspect": bool(rec.get("suspect"))}
    artist, title = LY.split_name(stem)
    uid = forced_uid or FP.fingerprint(p)
    if stored is None:
        stored = LRC.store_index({uid})
    if not _has_lyric(title, artist, uid, stored):
        e = {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
             "uid": uid,
             "file": str(p), "stem": stem, "orig": title, "group": group,
             "title": title, "artist": artist, "source": "", "lang": "unknown",
             "has_lyric": False, "suspect": False}
        LI.put(e)
        return e
    hit = LY.get_lrc(title, artist, use_cache=True, network=False) or {}
    e = {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
         "uid": uid,
         "has_lyric": True,
         "file": str(p), "stem": stem, "orig": title, "group": group,
         "title": hit.get("name") or title,
         "artist": hit.get("artist") or artist, "source": hit.get("source") or "",
         "lang": hit.get("lang") or "unknown",
         "suspect": (hit.get("lang") == "other" and bool(LY.JP.search(stem)))}
    LI.put(e)
    return e


def load_for_playlists() -> list[dict]:
    """启动只加载歌单引用的歌；索引失效时用 imports 补查。"""
    global LAST_MISSING

    uids = list(dict.fromkeys(PL.all_uids()))
    wanted = set(uids)
    if not wanted:
        LAST_MISSING = []
        return []

    resolved = FP.paths_for_uids(uids)
    indexed = LI.paths_by_uid()
    stored = LRC.store_index(uids)
    chosen: dict[str, Path] = {}
    stale_paths: list[str] = []
    for uid in uids:
        paths = [Path(x) for x in (resolved.get(uid) or []) + (indexed.get(uid) or [])]
        for p in paths:
            if p.is_file():
                if uid not in chosen:
                    chosen[uid] = p
            else:
                stale_paths.append(str(p))

    if stale_paths and roots_available():
        LI.prune_paths(stale_paths)
        FP.prune_paths(stale_paths)
    elif stale_paths:
        LI.set_meta({**LI.meta(), "last_offline": True})

    import_paths = {str(Path(str(r.get("audio") or "")).expanduser())
                    for r in load_imports() if r.get("audio")}

    def fill_from_imports(missing: set[str]) -> bool:
        """用 imports 里仍存在的路径补 missing；返回是否补了条目。"""
        if not missing:
            return False
        added = False
        for row in load_imports():
            if not missing:
                break
            p = Path(str(row.get("audio") or "")).expanduser()
            if not p.is_file():
                continue
            e = _entry(p, "导入", stored)
            if e and str(e["uid"]) in missing:
                chosen[str(e["uid"])] = p
                missing.discard(str(e["uid"]))
                added = True
        return added

    def collect() -> tuple[list[dict], set[str]]:
        out: list[dict] = []
        seen: set[str] = set()
        loaded: set[str] = set()
        for uid, p in sorted(chosen.items(), key=lambda x: str(x[1])):
            e = _entry(p, "导入" if str(p) in import_paths else (p.parent.name or "曲库"), stored)
            # 索引路径可能已经被替换成另一段音频；不能把新 uid 当成旧歌。
            if not e or str(e.get("uid")) != str(uid):
                continue
            if e["file"] in seen:
                continue
            seen.add(e["file"])
            loaded.add(str(uid))
            out.append(e)
        return out, loaded

    missing = wanted - set(chosen)
    fill_from_imports(missing)
    out, loaded_uids = collect()

    # 第一次补查时 chosen 里可能已有“存在但 uid 已变”的路径。
    # 校验后再补一次，避免直接掉到全量重建。
    missing = wanted - loaded_uids
    if missing and fill_from_imports(missing):
        out, loaded_uids = collect()
        missing = wanted - loaded_uids

    LAST_MISSING = sorted(str(u) for u in missing)
    diag.log("library", f"loaded {len(out)}/{len(uids)} missing={len(missing)}")
    LI.flush()
    FP.flush()
    return out


def should_auto_rebuild() -> bool:
    """有缺失才重建；离线后恢复、或缺失集合变化时重试。"""
    if not roots_available():
        return False
    if not LAST_MISSING:
        return False
    m = LI.meta()
    if m.get("last_offline"):
        return True
    if m.get("last_missing") == LAST_MISSING:
        return False
    return True


def rebuild_library() -> dict:
    """全量扫描并裁剪索引；只由缺失触发的自动维护调用。"""
    global LAST_MISSING
    old = set(LAST_MISSING)
    lib = scan_library()
    _publish(lib)
    loaded = {str(v.get("uid")) for v in CACHE.values()}
    LAST_MISSING = sorted(str(u) for u in (set(PL.all_uids()) - loaded))
    recovered = len(old - set(LAST_MISSING))
    meta = {"last_missing": LAST_MISSING, "last_rebuild": time.time(),
            "last_recovered": recovered}
    if not roots_available():
        meta["last_offline"] = True
        LI.set_meta(meta)
        LI.flush()
        return {"ok": True, "library": len(CACHE), "missing": len(LAST_MISSING),
                "recovered": recovered, "offline": True}
    LI.set_meta(meta)
    LI.flush()
    diag.log("library", f"rebuild loaded={len(CACHE)} missing={len(LAST_MISSING)} recovered={recovered}")
    return {"ok": True, "library": len(CACHE), "missing": len(LAST_MISSING),
            "recovered": recovered}


def load_cache_for_playlists() -> int:
    lib = load_for_playlists()
    _publish(lib)
    return len(CACHE)


def scan_library(folder: Path | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    stored = LRC.store_index()

    def add(p: Path, group: str) -> None:
        if p.suffix.lower() not in tuple(LB["extensions"]):
            return
        e = _entry(p, group, stored)
        if e and e["file"] not in seen:
            seen.add(e["file"])
            out.append(e)

    for root in ([folder] if folder else music_dirs()):
        for p in sorted(root.rglob("*")):
            add(p, root.name)

    for row in load_imports():                 # 导入过、但不在 music_dirs 里的歌
        p = Path(str(row.get("audio") or "")).expanduser()
        if p.is_file():
            add(p, "导入")

    if folder is None and roots_available():   # 显式扫临时目录 / 目录离线不裁剪全局索引
        valid = {e["file"] for e in out}
        LI.prune(valid)
        FP.prune(valid)
    LI.flush()
    FP.flush()
    return out
