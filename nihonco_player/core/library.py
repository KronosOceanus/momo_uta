#!/usr/bin/env python3
"""歌曲库：扫目录、读缓存、人工标签。只有文件和缓存，没有 HTTP。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nihonco_yomi.paths import ROOT

from . import lyrics as LY

MUSIC = Path.home() / "Music" / "网易云音乐"
IMPORTS = ROOT / "data" / "curated" / "imports.json"     # 导入的音频路径（不在 music_dirs 里也能列）
TAGS = ROOT / "data" / "curated" / "song_tags.json"

CACHE: dict = {}          # idx(str) -> 歌曲条目，启动时由 scan_library 填充
HIDDEN_TAGS = {"inst", "nonja"}


def load_tags() -> dict:
    try:
        return json.loads(TAGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_tags(d: dict) -> None:
    TAGS.parent.mkdir(parents=True, exist_ok=True)
    TAGS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")     # 翻译覆盖率低于此值 → 整首不显示译文


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


def _entry(p: Path, group: str) -> dict | None:
    stem = p.stem
    # 不再按"像不像日文歌"过滤：进了歌单就应该看得见。
    # 过滤只用于歌词匹配时的判断（is_likely_song 仍被匹配流程使用）。
    artist, title = LY.split_name(stem)
    has = LY._cached(title, artist)
    hit = LY.get_lrc(title, artist, use_cache=True) if has else None
    if not hit or (hit.get("source") != "local-lrc" and LY.content_lines(hit.get("lrc") or "") < 3):
        # 网络匹配要有足够的歌词行。本地草稿可以尚未打点，不应再次匹配。
        return {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
                "uid": hashlib.md5(str(p).encode()).hexdigest()[:12],
                "file": str(p), "stem": stem, "orig": title, "group": group,
                "title": title, "artist": artist, "source": "", "lang": "unknown",
                "has_lyric": False, "suspect": False}
    return {"key": hashlib.md5(stem.encode()).hexdigest()[:12],
            "uid": hashlib.md5(str(p).encode()).hexdigest()[:12],
            "has_lyric": True,
            "file": str(p), "stem": stem, "orig": title, "group": group,
            "title": hit.get("name") or title,
            "artist": hit.get("artist") or artist, "source": hit.get("source") or "",
            "lang": hit.get("lang") or "unknown",
            "suspect": (hit.get("lang") == "other" and bool(LY.JP.search(stem)))}


def scan_library(folder: Path | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(p: Path, group: str) -> None:
        if p.suffix.lower() not in (".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg"):
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

    return out
