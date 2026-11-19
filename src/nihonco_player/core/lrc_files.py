#!/usr/bin/env python3
"""LRC / nhlrc 文件层：路径、读写、备份、恢复、与歌词缓存同步。"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import lyrics as LY
from .lrc_doc import (NHLRC_MARK, NHLRC_VERSION, GEN, _parse_document,  # noqa: F401
                      _split_nhlrc, annotations_for, parse,
                      render, render_body, render_nhlrc)

def lrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".lrc")


def nhlrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".nhlrc")


def exists(audio: str | Path) -> bool:
    return nhlrc_path(audio).is_file() or lrc_path(audio).is_file()


def load(audio: str | Path) -> dict:
    """优先 .nhlrc，其次 .lrc，最后歌词缓存。"""
    audio = Path(audio)
    np_ = nhlrc_path(audio)
    lp = lrc_path(audio)
    from_cache = False
    if np_.is_file():
        full = np_.read_text(encoding="utf-8", errors="ignore")
        body, tail = _split_nhlrc(full)
        path, kind = np_, "nhlrc"
        if not any((ln.get("text") or "").strip()
                   for ln in _parse_document(body)[0]) and lp.is_file():
            body = lp.read_text(encoding="utf-8", errors="ignore")   # 空壳 nhlrc → 回退 lrc
            path, kind, tail = lp, "lrc", None
    elif lp.is_file():
        full = lp.read_text(encoding="utf-8", errors="ignore")
        body, tail = full, None
        path, kind = lp, "lrc"
    else:
        artist, title = LY.split_name(audio.stem)
        hit = LY.get_lrc(title, artist) or {}
        full = hit.get("lrc") or ""
        cached_ann = hit.get("nhlrc_annotations") or {}
        tail = {"lines": [{"i": int(i), "seg": seg} for i, seg in cached_ann.items()]} \
            if cached_ann else None
        body = full
        path, kind = np_, "cache"
        from_cache = bool(full)
    lines, metadata = _parse_document(body)
    annotations = annotations_for(lines, tail)
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "text": body, "lines": lines,
            "metadata": metadata, "annotations": annotations,
            "nhlrc": kind == "nhlrc"}


def backup_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".nhlrc.bak")


def backup_candidates(audio: str | Path) -> list[Path]:
    a = Path(audio)
    return [a.with_suffix(".nhlrc.bak"), a.with_suffix(".lrc.bak")]


def backup_status(audio: str | Path) -> dict:
    b = next((x for x in backup_candidates(audio) if x.is_file()), None)
    if not b:
        return {"exists": False}
    text = b.read_text(encoding="utf-8", errors="ignore")
    return {"exists": True, "path": str(b), "lines": len(parse(text)),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def restore_backup(audio: str | Path) -> dict:
    """把 .lrc.bak 覆盖回 .lrc（恢复最初版本），并同步歌词缓存。"""
    audio = Path(audio)
    b = next((x for x in backup_candidates(audio) if x.is_file()), None)
    if not b:
        return {"ok": False, "error": "没有备份文件"}
    p = nhlrc_path(audio)
    shutil.copy2(b, p)
    artist, title = LY.split_name(audio.stem)
    body, _ = _split_nhlrc(p.read_text(encoding="utf-8", errors="ignore"))
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(parse(p.read_text(encoding="utf-8")))}


def import_text(audio: str | Path, text: str) -> dict:
    """用外部 .lrc 文本覆盖当前歌词：写成 .nhlrc 正文（首次覆盖前备份）。"""
    audio = Path(audio)
    p = nhlrc_path(audio)
    p.parent.mkdir(parents=True, exist_ok=True)
    backed = False
    bak = backup_path(audio)
    src = nhlrc_path(audio) if nhlrc_path(audio).is_file() else lrc_path(audio)
    if src.is_file() and not bak.exists():
        shutil.copy2(src, bak)
        backed = True
    body, _tail = _split_nhlrc(text)          # 选到 .nhlrc 时只取正文
    body = body if body.endswith("\n") else body + "\n"
    p.write_text(body, encoding="utf-8")
    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(parse(body)), "backed_up": backed}


def save(audio: str | Path, lines: list[dict],
         annotations: dict[int, list] | None = None) -> dict:
    """写 .nhlrc（正文 + 尾部标注；首次备份成 .nhlrc.bak），并同步歌词缓存。"""
    audio = Path(audio)
    p = nhlrc_path(audio)
    p.parent.mkdir(parents=True, exist_ok=True)

    artist, title = LY.split_name(audio.stem)
    original = ""
    backed = False
    src = p if p.is_file() else lrc_path(audio)
    if src.is_file():
        original = src.read_text(encoding="utf-8", errors="ignore")
        bak = backup_path(audio)
        if not bak.exists():
            shutil.copy2(src, bak)
            backed = True
    elif LY._cached(title, artist):
        original = (LY.get_lrc(title, artist) or {}).get("lrc") or ""

    body, _tail = _split_nhlrc(original)
    _, metadata = _parse_document(body)
    if annotations is None:
        annotations = annotations_for(lines, _tail)
    text = render_nhlrc(lines, metadata, annotations)
    p.write_text(text, encoding="utf-8")
    LY.write_local_lrc(title, artist, render_body(lines, metadata),
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(lines), "backed_up": backed}
