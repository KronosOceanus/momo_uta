#!/usr/bin/env python3
"""歌曲库：扫目录、读缓存、人工标签。只有文件和缓存，没有 HTTP。"""
from __future__ import annotations

import hashlib
import threading
import json
import time
from pathlib import Path

from nihonco_yomi.config import LB
from nihonco_yomi.paths import ROOT

from . import diag
from . import fingerprint as FP
from . import library_index as LI
from . import lrc_files as LRC
from . import lyrics as LY

MUSIC = Path.home() / "Music" / "网易云音乐"
IMPORTS = ROOT / "data" / "curated" / "imports.json"     # 导入的音频路径（不在 music_dirs 里也能列）
CACHE: dict = {}          # idx(str) -> 歌曲条目
LAST_MISSING: list[str] = []   # 最近一次加载未解析到的歌单 uid

def music_dirs() -> list[Path]:
    from nihonco_yomi.config import PL
    dirs = PL.get("music_dirs") or [str(MUSIC)]
    return [Path(str(d)).expanduser() for d in dirs]


def load_imports() -> list[dict]:
    try:
        return json.loads(IMPORTS.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_import(audio: str, title: str, artist: str) -> None:
    rows = load_imports()
    if any(r.get("audio") == audio for r in rows):
        return
    rows.append({"audio": audio, "title": title, "artist": artist})
    IMPORTS.parent.mkdir(parents=True, exist_ok=True)
    IMPORTS.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


_LOCK = threading.RLock()


def _resolve_uid(uid: str) -> tuple[Path, str] | None:
    """按已有索引/imports 找 uid；找不到返回 None，绝不扫全库。"""
    from . import playlists as PL
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
    with _LOCK:
        if uid is not None:
            for k, v in list(CACHE.items()):
                if str(v.get("uid")) == str(uid):
                    e = _entry(Path(v["file"]), v.get("group", ""))
                    if e:
                        CACHE[k] = e
                    LI.flush()
                    return len(CACHE)
            found = _resolve_uid(str(uid))
            if found:
                p, group = found
                e = _entry(p, group)
                if e:
                    nums = [int(k) for k in CACHE if str(k).isdigit()]
                    CACHE[str(max(nums) + 1 if nums else 0)] = e
            LI.flush()
            return len(CACHE)
        lib = scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})
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
    hit = LY.get_lrc(title, artist, use_cache=True) or {}
    lrc = hit.get("lrc") or ""
    if hit.get("source") == "local-lrc":
        return bool(lrc.strip())
    return (LY.content_lines(lrc) >= int(LY.CFG["min_content_lines"]) and LY.has_timed(lrc))


def _entry(p: Path, group: str, stored=None) -> dict | None:
    stem = p.stem
    # 不再按"像不像日文歌"过滤：进了歌单就应该看得见。
    # 过滤只用于歌词匹配时的判断（is_likely_song 仍被匹配流程使用）。
    rec = LI.get(p)
    if rec:
        return {"key": rec.get("key") or hashlib.md5(stem.encode()).hexdigest()[:12],
                "uid": rec["uid"], "file": str(p), "stem": rec.get("stem") or stem,
                "orig": rec.get("orig") or rec.get("title") or stem,
                "group": group or rec.get("group", ""),
                "title": rec.get("title") or stem,
                "artist": rec.get("artist", ""),
                "source": rec.get("source", ""),
                "lang": rec.get("lang") or "unknown",
                "has_lyric": _has_lyric(*LY.split_name(rec.get("stem") or stem),
                                        uid=rec["uid"], stored=stored),
                "suspect": bool(rec.get("suspect"))}
    artist, title = LY.split_name(stem)
    uid = FP.fingerprint(p)
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
    hit = LY.get_lrc(title, artist, use_cache=True) or {}
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
    """启动只加载歌单引用的歌，不再加载无关 imports。"""
    global LAST_MISSING
    from . import playlists as PL

    uids = list(dict.fromkeys(PL.all_uids()))
    wanted = set(uids)
    if not wanted:
        return []

    resolved = FP.paths_for_uids(uids)
    indexed = LI.paths_by_uid()
    stored = LRC.store_index(uids)
    chosen: dict[str, Path] = {}
    for uid in uids:
        paths = [Path(x) for x in (resolved.get(uid) or []) + (indexed.get(uid) or [])]
        for p in paths:
            if p.is_file():
                chosen[uid] = p
                break

    missing = wanted - set(chosen)
    if missing:                                  # 索引没有 → 只从 imports 里补
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

    out: list[dict] = []
    seen: set[str] = set()
    import_paths = {str(Path(str(r.get("audio") or "")).expanduser())
                    for r in load_imports() if r.get("audio")}
    for uid, p in sorted(chosen.items(), key=lambda x: str(x[1])):
        e = _entry(p, "导入" if str(p) in import_paths else (p.parent.name or "曲库"), stored)
        if e and e["file"] not in seen:
            seen.add(e["file"])
            out.append(e)
    LAST_MISSING = sorted(str(u) for u in missing)
    diag.log("library", f"loaded {len(out)}/{len(uids)} missing={len(missing)}")
    LI.flush()
    FP.flush()
    return out


def should_auto_rebuild() -> bool:
    """有缺失才重建；同一缺失集合且上次没找回，就不再自动重试。"""
    if not LAST_MISSING:
        return False
    m = LI.meta()
    if m.get("last_missing") == LAST_MISSING:
        return False
    return True


def rebuild_library() -> dict:
    """全量扫描并裁剪索引；只由缺失触发的自动维护调用。"""
    global LAST_MISSING
    from . import playlists as PL
    old = set(LAST_MISSING)
    lib = scan_library()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
    loaded = {str(v.get("uid")) for v in CACHE.values()}
    LAST_MISSING = sorted(str(u) for u in (set(PL.all_uids()) - loaded))
    recovered = len(old - set(LAST_MISSING))
    LI.set_meta({"last_missing": LAST_MISSING, "last_rebuild": time.time(),
                 "last_recovered": recovered})
    LI.flush()
    diag.log("library", f"rebuild loaded={len(CACHE)} missing={len(LAST_MISSING)} recovered={recovered}")
    return {"ok": True, "library": len(CACHE), "missing": len(LAST_MISSING),
            "recovered": recovered}


def load_cache_for_playlists() -> int:
    lib = load_for_playlists()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
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
        p = Path(row["audio"]).expanduser()
        if p.exists():
            add(p, "导入")

    if folder is None:                         # 显式扫临时目录不裁剪全局索引
        valid = {e["file"] for e in out}
        LI.prune(valid)
        FP.prune(valid)
    LI.flush()
    FP.flush()
    return out
