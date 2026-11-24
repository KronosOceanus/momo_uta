#!/usr/bin/env python3
"""导入：扫描目录，把音频和 .lrc 配对，直接写权威 nhlrc。

不复制文件，不联网——只把「本地已有的 lrc」变成这个软件的歌词来源。
"""
from __future__ import annotations

import re
import unicodedata
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


def _lyric_base(p: Path) -> str:
    return p.name[:-len(p.suffix)]


def _exact_key(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s)).strip().casefold()


def _choose(cands: list[Path]) -> tuple[Path | None, list[Path]]:
    """同一 base 的 .lrc/.nhlrc 可以共存；不同 base 才是歧义。"""
    if not cands:
        return None, []
    bases = {_exact_key(_lyric_base(p)) for p in cands}
    if len(bases) == 1:
        return _pick(cands), []
    return None, cands


def _match_audio(audio: Path, lrcs: list[Path], used: set[Path]) -> tuple[Path | None, list[Path]]:
    # 同目录优先，再全局；精确 stem 优先，再归一化 stem。
    for same_dir in (True, False):
        for keyfn in (_exact_key, _stem_key):
            cand = [p for p in lrcs if p not in used
                    and (not same_dir or p.parent == audio.parent)
                    and keyfn(_lyric_base(p)) == keyfn(audio.stem)]
            if cand:
                return _choose(cand)
    return None, []


def _match_lrc(lrc: Path, audios: list[Path], used: set[Path]) -> tuple[Path | None, list[Path]]:
    for same_dir in (True, False):
        for keyfn in (_exact_key, _stem_key):
            cand = [a for a in audios if a not in used
                    and (not same_dir or a.parent == lrc.parent)
                    and keyfn(a.stem) == keyfn(_lyric_base(lrc))]
            if cand:
                return _choose(cand)
    return None, []


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
    if with_lrc:
        for a in audios:                         # 只选音频时也找同目录歌词
            for p in a.parent.glob("*"):
                if p.suffix.lower() in LYRIC_EXT:
                    lrcs.append(p)
    lrcs = _unique_paths(lrcs)
    rejected = _unique_paths(rejected)

    added, pending, overwritten, unpaired = [], [], 0, 0
    ambiguous = 0
    failed = []
    used_lrc: set[Path] = set()
    assigned: dict[Path, Path] = {}
    ambiguous_audio: set[Path] = set()
    remaining = list(audios)

    # 先同目录精确，再全局精确；然后才归一化匹配。避免 Track 1 抢走 Track 2 的 LRC。
    for same_dir in (True, False):
        for keyfn in (_exact_key, _stem_key):
            still = []
            for a in remaining:
                cand = [p for p in lrcs if p not in used_lrc
                        and (not same_dir or p.parent == a.parent)
                        and keyfn(_lyric_base(p)) == keyfn(a.stem)]
                lrc, bad = _choose(cand)
                if lrc:
                    used_lrc.add(lrc)
                    assigned[a] = lrc
                elif bad:
                    ambiguous += 1
                    ambiguous_audio.add(a)
                    pending.append(str(a))
                    added.append(str(a))
                    failed.append({"audio": str(a), "lrc": "",
                                   "error": "多个歌词候选，未自动配对"})
                else:
                    still.append(a)
            remaining = still

    for a in audios:                                # ② 音频 + lrc 配对
        if a in ambiguous_audio:
            continue
        lrc = assigned.get(a)
        if not lrc:
            pending.append(str(a))                  # ③ 只给音频 → 也进歌单，懒匹配
            added.append(str(a))
            continue
        artist, title = LY.split_name(a.stem)
        raw = lrc.read_text(encoding="utf-8", errors="ignore")
        ok, _why = LRC.valid_import(raw)
        if not ok:
            pending.append(str(a))
            added.append(str(a))
            continue
        had = LRC.exists(str(a))
        try:
            imported = LRC.import_text(str(a), raw, uid=FP.fingerprint(a),
                                       title=title, artist=artist)
        except Exception as e:
            imported = {"ok": False, "error": str(e)}
        if imported.get("ok"):
            if had:
                overwritten += 1
            added.append(str(a))
        else:
            # 音频本身有效；歌词失败也要让歌进库并待匹配。
            if str(a) not in added:
                added.append(str(a))
            if str(a) not in pending:
                pending.append(str(a))
            failed.append({"audio": str(a), "lrc": str(lrc),
                           "error": imported.get("error") or "歌词导入失败"})

    pool = [Path(x) for x in (pool_audio or [])]
    pool += [a for a in audios if str(a) not in added]
    used_audio: set[Path] = {Path(x['audio']) for x in failed if x.get('audio')}
    for lrc in lrcs if with_lrc else ():            # ④ 剩余 lrc → 反查音频
        if lrc in used_lrc:
            continue
        target, cand = _match_lrc(lrc, pool, used_audio)
        if not target:
            if cand:
                ambiguous += 1
                failed.append({"audio": "", "lrc": str(lrc),
                               "error": "多个音频候选，未自动配对"})
            unpaired += 1
            continue
        used_audio.add(target)
        artist, title = LY.split_name(target.stem)
        raw = lrc.read_text(encoding="utf-8", errors="ignore")
        ok, _why = LRC.valid_import(raw)
        if not ok:
            unpaired += 1
            continue
        had = LRC.exists(target)
        try:
            imported = LRC.import_text(str(target), raw, uid=FP.fingerprint(target),
                                       title=title, artist=artist)
        except Exception as e:
            imported = {"ok": False, "error": str(e)}
        used_lrc.add(lrc)
        if imported.get("ok"):
            if had:
                overwritten += 1
            else:
                added.append(str(target))
        else:
            if str(target) not in added:
                added.append(str(target))
            if str(target) not in pending:
                pending.append(str(target))
            failed.append({"audio": str(target), "lrc": str(lrc),
                           "error": imported.get("error") or "歌词导入失败"})

    return {"added": added, "pending": pending, "overwritten": overwritten,
            "unpaired": unpaired, "ambiguous": ambiguous,
            "rejected_lrc": len(rejected),
            "failed": failed, "failed_count": len(failed),
            "audio_found": len(audios), "lrc_found": len(lrcs)}
