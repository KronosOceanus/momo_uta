#!/usr/bin/env python3
"""LRC / nhlrc 文件层：路径、读写、备份、恢复、与歌词缓存同步。

标注文件统一放在 data/lyrics/<歌名> - <歌手>.<指纹>.nhlrc（不进音乐目录）。
身份只用音频指纹。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import threading
from pathlib import Path

from nihonco_yomi.paths import LYRICS

from . import diag
from . import fingerprint as FP
from . import lyrics as LY
from .lrc_doc import (NHLRC_MARK, NHLRC_VERSION, GEN, _hash8,  # noqa: F401
                      _parse_document, _split_nhlrc, annotations_for, parse,
                      render, render_body, render_nhlrc)

# 同一首歌的"读-改-写"串行化（HTTP 是多线程的）
LOCK = threading.RLock()


def uid_of(audio: str | Path) -> str:
    """和 library 里一致的 uid：音频指纹（读不了文件时退回路径哈希）。"""
    return FP.fingerprint(audio)


BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME_BYTES = 120


def _safe_name(text: str) -> str:
    s = BAD_CHARS.sub("_", text or "")
    return re.sub(r"\s+", " ", s).strip().strip(".")


def _truncate_bytes(text: str, limit: int) -> str:
    while text and len(text.encode("utf-8")) > limit:
        text = text[:-1]
    return text.rstrip(" .")


def _find(uid: str, suffix: str) -> Path | None:
    """按 uid 找已有文件（前缀可读，uid 在后）。"""
    for p in LYRICS.glob(f"*.{uid}{suffix}"):
        return p
    return None


def store_name(title: str, artist: str, uid: str) -> str:
    parts = [x.strip() for x in (title, artist) if x and x.strip()]
    base = _safe_name(" - ".join(parts)) or "untitled"
    return f"{_truncate_bytes(base, MAX_NAME_BYTES)}.{uid}.nhlrc"


def store_path(audio: str | Path, uid: str | None = None,
               title: str | None = None, artist: str | None = None) -> Path:
    u = uid or uid_of(audio)
    found = _find(u, ".nhlrc")
    if found:
        return found
    if title is None or artist is None:
        a_artist, a_title = LY.split_name(Path(audio).stem)
        title = title if title is not None else a_title
        artist = artist if artist is not None else a_artist
    return LYRICS / store_name(title or "", artist or "", u)


def store_backup(audio: str | Path, uid: str | None = None,
                 title: str | None = None, artist: str | None = None) -> Path:
    u = uid or uid_of(audio)
    found = _find(u, ".nhlrc.bak")
    if found:
        return found
    return store_path(audio, u, title, artist).with_suffix(".nhlrc.bak")


def exists(audio: str | Path, uid: str | None = None) -> bool:
    return store_path(audio, uid or uid_of(audio)).is_file()


def load(audio: str | Path, uid: str | None = None,
         title: str | None = None, artist: str | None = None) -> dict:
    """优先 data/lyrics 下的 nhlrc；没有就用歌词缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    from_cache = False
    tail = None

    if sp.is_file():
        full = sp.read_text(encoding="utf-8", errors="ignore")
        body, tail = _split_nhlrc(full)
        path, kind = sp, "nhlrc"
    else:
        artist, title = LY.split_name(audio.stem)
        hit = LY.get_lrc(title, artist) or {}
        full = hit.get("lrc") or ""
        cached_ann = hit.get("nhlrc_annotations") or {}
        tail = {"lines": [{"i": int(i), "seg": seg} for i, seg in cached_ann.items()]} \
            if cached_ann else None
        body = full
        path, kind = sp, "cache"
        from_cache = bool(full)

    lines, metadata = _parse_document(body)
    # 整篇正文哈希一致 → 跳过逐行哈希比对（仍校验下标与拼接）
    strict = not (tail and tail.get("body") and tail["body"] == _hash8(body))
    annotations = annotations_for(lines, tail, strict=strict)
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "text": body, "lines": lines,
            "metadata": metadata, "annotations": annotations,
            "nhlrc": kind == "nhlrc"}


def backup_path(audio: str | Path, uid: str | None = None,
                title: str | None = None, artist: str | None = None) -> Path:
    return store_backup(audio, uid or uid_of(audio), title, artist)


def backup_candidates(audio: str | Path, uid: str | None = None,
                      title: str | None = None, artist: str | None = None) -> list[Path]:
    return [store_backup(audio, uid or uid_of(audio), title, artist)]


def backup_status(audio: str | Path, uid: str | None = None,
                  title: str | None = None, artist: str | None = None) -> dict:
    b = next((x for x in backup_candidates(audio, uid, title, artist) if x.is_file()), None)
    if not b:
        return {"exists": False}
    text = b.read_text(encoding="utf-8", errors="ignore")
    return {"exists": True, "path": str(b), "lines": len(parse(text)),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def restore_backup(audio: str | Path, uid: str | None = None,
                   title: str | None = None, artist: str | None = None) -> dict:
    """把备份覆盖回 data/lyrics/<uid>.nhlrc（恢复最初版本），并同步歌词缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    b = next((x for x in backup_candidates(audio, u, title, artist) if x.is_file()), None)
    if not b:
        return {"ok": False, "error": "没有备份文件"}
    sp = store_path(audio, u, title, artist)
    sp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b, sp)
    artist, title = LY.split_name(audio.stem)
    body, _ = _split_nhlrc(sp.read_text(encoding="utf-8", errors="ignore"))
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(sp), "lines": len(parse(sp.read_text(encoding="utf-8")))}


def import_text(audio: str | Path, text: str, uid: str | None = None,
                title: str | None = None, artist: str | None = None) -> dict:
    """用外部歌词文本覆盖当前歌词：写 data/lyrics/<uid>.nhlrc 的正文。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    sp.parent.mkdir(parents=True, exist_ok=True)
    backed = False
    bak = store_backup(audio, u, title, artist)
    src = sp
    if src.is_file() and not bak.exists():
        shutil.copy2(src, bak)
        backed = True
    body, tail = _split_nhlrc(text)
    body = body if body.endswith("\n") else body + "\n"
    lines, metadata = _parse_document(body)
    # 导入别人的 nhlrc：正文 + 读音一起搬（读音按行内容对齐），
    # 身份由当前音频的指纹决定，文件里不存来源信息
    annotations = annotations_for(lines, tail) if tail else {}
    out = render_nhlrc(lines, metadata, annotations) if annotations else body
    sp.write_text(out, encoding="utf-8")
    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(sp), "lines": len(lines),
            "annotated": len(annotations), "backed_up": backed}


def save(audio: str | Path, lines: list[dict],
         annotations: dict[int, list] | None = None,
         uid: str | None = None,
         title: str | None = None, artist: str | None = None) -> dict:
    """写 data/lyrics/<uid>.nhlrc（正文 + 尾部），首次备份成 .nhlrc.bak。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    sp.parent.mkdir(parents=True, exist_ok=True)

    artist, title = LY.split_name(audio.stem)
    original = ""
    backed = False
    src = sp
    if src.is_file():
        original = src.read_text(encoding="utf-8", errors="ignore")
        bak = store_backup(audio, u, title, artist)
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
    sp.write_text(text, encoding="utf-8")
    LY.write_local_lrc(title, artist, render_body(lines, metadata),
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(sp), "lines": len(lines), "backed_up": backed}
