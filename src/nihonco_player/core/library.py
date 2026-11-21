#!/usr/bin/env python3
"""歌曲库：扫目录、读缓存、人工标签。只有文件和缓存，没有 HTTP。"""
from __future__ import annotations

import hashlib
import threading
import json
from pathlib import Path

from nihonco_yomi.config import LB
from nihonco_yomi.paths import ROOT

from . import fingerprint as FP
from . import lyrics as LY

MUSIC = Path.home() / "Music" / "网易云音乐"
IMPORTS = ROOT / "data" / "curated" / "imports.json"     # 导入的音频路径（不在 music_dirs 里也能列）
CACHE: dict = {}          # idx(str) -> 歌曲条目，启动时由 scan_library 填充

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


def refresh(uid: str | None = None) -> int:
    """重建 CACHE。

    uid 在索引里 → 只重算这一条（不扫全库、不改其它条目的序号）；
    uid 不在索引里（新导入的歌）→ 全量重建。
    """
    with _LOCK:
        if uid is not None:
            for k, v in list(CACHE.items()):
                if str(v.get("uid")) == str(uid):
                    e = _entry(Path(v["file"]), v.get("group", ""))
                    if e:
                        CACHE[k] = e
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
    FP.flush()
    return out


def _entry(p: Path, group: str) -> dict | None:
    stem = p.stem
    # 不再按"像不像日文歌"过滤：进了歌单就应该看得见。
    # 过滤只用于歌词匹配时的判断（is_likely_song 仍被匹配流程使用）。
    artist, title = LY.split_name(stem)
    has = LY._cached(title, artist)
    hit = LY.get_lrc(title, artist, use_cache=True) if has else None
    if hit and hit.get("source") == "local-lrc" and not (hit.get("lrc") or "").strip():
        hit = None                            # 空文件（比如误存的空壳）当作没有歌词
    if not hit or (hit.get("source") != "local-lrc" and LY.content_lines(hit.get("lrc") or "") < 3):
        # 网络匹配要有足够的歌词行。本地草稿可以尚未打点，不应再次匹配。
        return {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
                "uid": FP.fingerprint(p),
                "file": str(p), "stem": stem, "orig": title, "group": group,
                "title": title, "artist": artist, "source": "", "lang": "unknown",
                "has_lyric": False, "suspect": False}
    return {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
            "uid": FP.fingerprint(p),
            "has_lyric": True,
            "file": str(p), "stem": stem, "orig": title, "group": group,
            "title": hit.get("name") or title,
            "artist": hit.get("artist") or artist, "source": hit.get("source") or "",
            "lang": hit.get("lang") or "unknown",
            "suspect": (hit.get("lang") == "other" and bool(LY.JP.search(stem)))}


def load_for_playlists() -> list[dict]:
    """只加载歌单成员和 imports，不递归扫 music_dirs。

    索引缺失/有 uid 解析不到时，退回一次全量扫描，保证不丢歌。
    """
    from . import playlists as PL

    uids = PL.all_uids()
    resolved = FP.paths_for_uids(uids)
    imports = [Path(r["audio"]).expanduser() for r in load_imports()
               if r.get("audio") and Path(r["audio"]).expanduser().is_file()]

    chosen: dict[str, Path] = {}
    for uid in uids:
        paths = resolved.get(uid) or []
        if paths:
            chosen[uid] = Path(paths[0])       # 同一 uid 多份拷贝时取第一份
    out: list[dict] = []
    seen_files: set[str] = set()
    loaded_uids: set[str] = set()

    def add(p: Path, group: str) -> None:
        p = p.expanduser()
        if not p.is_file() or str(p) in seen_files:
            return
        e = _entry(p, group)
        if not e or e["file"] in seen_files:
            return
        seen_files.add(e["file"])
        loaded_uids.add(str(e["uid"]))
        out.append(e)

    for uid, p in sorted(chosen.items(), key=lambda x: str(x[1])):
        add(p, p.parent.name or "曲库")
    for p in imports:
        if str(p) not in seen_files:
            add(p, "导入")

    missing = {str(u) for u in uids} - loaded_uids
    if missing:
        return scan_library()                 # 索引缺失/文件移动 → 一次兜底
    FP.flush()
    return out


def load_cache_for_playlists() -> int:
    lib = load_for_playlists()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
    return len(CACHE)


def scan_library(folder: Path | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(p: Path, group: str) -> None:
        if p.suffix.lower() not in tuple(LB["extensions"]):
            return
        e = _entry(p, group)
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

    FP.flush()
    return out
