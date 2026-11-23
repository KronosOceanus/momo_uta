#!/usr/bin/env python3
"""导入：扫描目录，把音频和 .lrc 配对，直接写权威 nhlrc。

不复制文件，不联网——只把「本地已有的 lrc」变成这个软件的歌词来源。
"""
from __future__ import annotations

import re
from pathlib import Path

from momo_yomi.config import LB

from . import fingerprint as FP
from . import lrc_files as LRC
from . import lyrics as LY

AUDIO_EXT = set(LB["extensions"])
LYRIC_EXT = {".lrc", ".nhlrc"}


def _pick(cands: list[Path]) -> Path | None:
    """同一首歌有多个歌词文件时：nhlrc 优先，其次较新的。"""
    if not cands:
        return None
    return sorted(cands, key=lambda p: (p.suffix.lower() == ".nhlrc",
                                        p.stat().st_mtime))[-1]


JUNK = re.compile(r"[\s._\-]*[\(（\[【]\s*(?:\d+|mqms\d*|tv\s*size|short\s*ver\.?|"
                  r"ショートサイズ)\s*[\)）\]】]$", re.I)


def _stem_key(s: str) -> str:
    """用来配对的主干：去扩展名式的后缀、去编号、去符号、小写。"""
    s = JUNK.sub("", s)
    s = re.sub(r"^[\s\d._\-]+", "", s)
    return LY._norm(s)


def _unique_paths(items):
    seen = set()
    out = []
    for p in items:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def import_paths(paths: list[str], pool_audio: list[str] | None = None,
                 with_lrc: bool = False) -> dict:
    """按用户选中的路径导一批。

    with_lrc=False：只收音频，不扫描/不配对目录里的歌词。
    with_lrc=True：显式允许本地 LRC/NHLRC 配对。

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
    rejected = [p for p in files if not with_lrc and p.suffix.lower() in LYRIC_EXT]
    lrcs = [p for p in files if with_lrc and p.suffix.lower() in LYRIC_EXT]
    for d in dirs:                                  # ① 目录递归
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in AUDIO_EXT:
                audios.append(p)
            elif with_lrc and p.suffix.lower() in LYRIC_EXT:
                lrcs.append(p)

    audios = _unique_paths(audios)
    lrcs = _unique_paths(lrcs)
    rejected = _unique_paths(rejected)

    by_key: dict[str, list[Path]] = {}
    for p in lrcs:
        by_key.setdefault(_stem_key(p.stem), []).append(p)

    added, pending, overwritten, unpaired = [], [], 0, 0
    used_lrc: set[Path] = set()

    for a in audios:                                # ② 音频 + lrc 配对
        key = _stem_key(a.stem)
        cand = [p for p in by_key.get(key, []) if p not in used_lrc] if with_lrc else []
        if not cand and with_lrc:                    # 音频自己所在目录里找同名歌词
            cand = [p for p in a.parent.glob("*")
                    if p.suffix.lower() in LYRIC_EXT and p not in used_lrc
                    and _stem_key(p.stem) == key]
        if not cand and with_lrc:                    # 再退：同目录唯一 lrc
            same = [p for p in lrcs if p.parent == a.parent and p not in used_lrc]
            cand = same if len(same) == 1 else []
        if not cand:
            pending.append(str(a))                  # ③ 只给音频 → 也进歌单，懒匹配
            added.append(str(a))
            continue
        lrc = _pick(cand)
        used_lrc.add(lrc)
        artist, title = LY.split_name(a.stem)
        raw = lrc.read_text(encoding="utf-8", errors="ignore")
        ok, _why = LRC.valid_import(raw)
        if not ok:
            pending.append(str(a))
            added.append(str(a))
            continue
        had = LRC.exists(str(a))
        imported = LRC.import_text(str(a), raw, uid=FP.fingerprint(a),
                                   title=title, artist=artist)
        if imported.get("ok"):
            if had:
                overwritten += 1
            added.append(str(a))
        else:
            pending.append(str(a))

    pool = [Path(x) for x in (pool_audio or [])]
    pool += [a for a in audios if str(a) not in added]
    for lrc in lrcs if with_lrc else ():            # ④ 剩余 lrc → 反查音频
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
        raw = lrc.read_text(encoding="utf-8", errors="ignore")
        ok, _why = LRC.valid_import(raw)
        if not ok:
            unpaired += 1
            continue
        had = LRC.exists(target)
        imported = LRC.import_text(str(target), raw, uid=FP.fingerprint(target),
                                   title=title, artist=artist)
        used_lrc.add(lrc)
        if imported.get("ok"):
            if had:
                overwritten += 1
            else:
                added.append(str(target))

    return {"added": added, "pending": pending, "overwritten": overwritten,
            "unpaired": unpaired, "rejected_lrc": len(rejected),
            "audio_found": len(audios), "lrc_found": len(lrcs)}
