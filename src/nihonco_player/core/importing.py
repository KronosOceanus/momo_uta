#!/usr/bin/env python3
"""导入：扫描目录，把音频和 .lrc 配对，预览后写入缓存。

不复制文件，不联网——只把「本地已有的 lrc」变成这个软件的歌词来源。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nihonco_yomi.config import LB

from . import library as LIB
from . import lrc_doc as DOC
from . import lyrics as LY

AUDIO_EXT = set(LB["extensions"])
PAIR_LRC = bool(LB["auto_pair_lrc"])
LYRIC_EXT = {".lrc", ".nhlrc"}


def _pick(cands: list[Path]) -> Path | None:
    """同一首歌有多个歌词文件时：nhlrc 优先，其次较新的。"""
    if not cands:
        return None
    return sorted(cands, key=lambda p: (p.suffix.lower() == ".nhlrc",
                                        p.stat().st_mtime))[-1]


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return DOC._split_nhlrc(text)[0] if path.suffix.lower() == ".nhlrc" else text


def _annotations(path: Path, body: str) -> dict | None:
    if path.suffix.lower() != ".nhlrc":
        return None
    _b, tail = DOC._split_nhlrc(path.read_text(encoding="utf-8", errors="ignore"))
    if not tail:
        return None
    lines, _m = DOC._parse_document(body)
    return DOC.annotations_for(lines, tail) or None
JUNK = re.compile(r"[\s._\-]*[\(（\[【]\s*(?:\d+|mqms\d*|tv\s*size|short\s*ver\.?|"
                  r"ショートサイズ)\s*[\)）\]】]$", re.I)


def _stem_key(s: str) -> str:
    """用来配对的主干：去扩展名式的后缀、去编号、去符号、小写。"""
    s = JUNK.sub("", s)
    s = re.sub(r"^[\s\d._\-]+", "", s)
    return LY._norm(s)


def _pair(audios: list[Path], lrcs: list[Path], root: Path | None = None) -> dict:
    by_stem: dict[str, list[Path]] = {}
    for p in lrcs:
        by_stem.setdefault(_stem_key(p.stem), []).append(p)

    items, unpaired = [], 0
    for a in audios:
        key = _stem_key(a.stem)
        cand = by_stem.get(key) or []
        if not cand:                       # 退化：同目录下唯一一个歌词文件
            same_dir = [p for p in lrcs if p.parent == a.parent]
            cand = same_dir if len(same_dir) == 1 else []
        rel = (a.relative_to(root) if root and a.is_relative_to(root) else a.name)
        if not cand:
            unpaired += 1
            artist, title = LY.split_name(a.stem)
            items.append({"stem": a.stem, "audio": str(a), "lrc": None, "rel": str(rel),
                          "title": title, "artist": artist,
                          "duration": round(LY.audio_duration(a), 1),
                          "lines": 0, "status": "需联网匹配"})
            continue
        lrc = _pick(cand)
        text = _body(lrc)
        lines = LY.content_lines(text)
        artist, title = LY.split_name(a.stem)
        items.append({
            "stem": a.stem, "audio": str(a), "lrc": str(lrc), "rel": str(rel),
            "title": title, "artist": artist,
            "duration": round(LY.audio_duration(a), 1),
            "lines": lines,
            "status": ("就绪" if lines >= 3 else f"歌词只有 {lines} 行"),
        })

    ready = [i for i in items if i["status"] in ("就绪", "需联网匹配")]
    return {"audio_found": len(audios), "lrc_found": len(lrcs),
            "ready": len(ready), "unpaired": unpaired, "items": items}




def import_paths(paths: list[str], pool_audio: list[str] | None = None) -> dict:
    """按用户选中的路径（可以混着是目录和文件）导一批。

    返回 {added:[audio str], pending:[audio str], overwritten:int,
          unpaired:int, skipped:list[str]}
    """
    dirs, files = [], []
    for raw in paths:
        p = Path(str(raw)).expanduser()
        if p.is_dir():
            dirs.append(p)
        elif p.is_file():
            files.append(p)

    audios = [p for p in files if p.suffix.lower() in AUDIO_EXT]
    lrcs = [p for p in files if p.suffix.lower() in LYRIC_EXT]
    for d in dirs:                                  # ① 目录递归
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in AUDIO_EXT:
                audios.append(p)
            elif p.suffix.lower() in LYRIC_EXT:
                lrcs.append(p)

    by_key: dict[str, list[Path]] = {}
    for p in lrcs:
        by_key.setdefault(_stem_key(p.stem), []).append(p)

    added, pending, overwritten, unpaired = [], [], 0, 0
    used_lrc: set[Path] = set()

    for a in audios:                                # ② 音频 + lrc 配对
        key = _stem_key(a.stem)
        cand = [p for p in by_key.get(key, []) if p not in used_lrc] if PAIR_LRC else []
        if not cand:                                # 音频自己所在目录里找同名歌词
            cand = [p for p in a.parent.glob("*")
                    if p.suffix.lower() in LYRIC_EXT and p not in used_lrc
                    and _stem_key(p.stem) == key]
        if not cand:                                # 再退：同目录唯一 lrc
            same = [p for p in lrcs if p.parent == a.parent and p not in used_lrc]
            cand = same if len(same) == 1 else []
        if not cand:
            pending.append(str(a))                  # ③ 只给音频 → 也进歌单，懒匹配
            added.append(str(a))
            continue
        lrc = _pick(cand)
        used_lrc.add(lrc)
        artist, title = LY.split_name(a.stem)
        text = _body(lrc)
        if LY.content_lines(text) < 3:
            pending.append(str(a))
            added.append(str(a))
            continue
        ann = _annotations(lrc, text)
        LY.write_local_lrc(title, artist, text, annotations=ann,
                           duration=LY.audio_duration(a), name=title, by=artist)
        added.append(str(a))

    pool = [Path(x) for x in (pool_audio or [])]
    pool += [a for a in audios if str(a) not in added]
    for lrc in lrcs:                                # ④ 剩余 lrc → 反查音频
        if lrc in used_lrc:
            continue
        key = _stem_key(lrc.stem)
        target = next((a for a in pool if _stem_key(a.stem) == key), None) \
            or next((p for p in lrc.parent.glob("*")
                     if p.suffix.lower() in AUDIO_EXT and _stem_key(p.stem) == key), None)
        if not target:
            unpaired += 1
            continue
        artist, title = LY.split_name(target.stem)
        text = _body(lrc)
        if LY.content_lines(text) < 3:
            unpaired += 1
            continue
        had = LY._cached(title, artist) and LY.content_lines(
            (LY.get_lrc(title, artist, use_cache=True) or {}).get("lrc") or "") >= 3
        LY.write_local_lrc(title, artist, text, annotations=_annotations(lrc, text),
                           duration=LY.audio_duration(target), name=title, by=artist)
        used_lrc.add(lrc)
        if had:
            overwritten += 1
        else:
            added.append(str(target))

    return {"added": added, "pending": pending, "overwritten": overwritten,
            "unpaired": unpaired, "audio_found": len(audios), "lrc_found": len(lrcs)}
