#!/usr/bin/env python3
"""LRC / nhlrc 文件层：路径、读写、备份、恢复、与歌词缓存同步。

标注文件统一放在 data/lyrics/<uid>.nhlrc（不进音乐目录）。
读取兼容旧的"音频旁边同名 .nhlrc/.lrc"：读到旧 .nhlrc 时复制进新目录并删除旧文件。
"""
from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path

from nihonco_yomi.paths import LYRICS

from . import diag
from . import lyrics as LY
from .lrc_doc import (NHLRC_MARK, NHLRC_VERSION, GEN, _hash8,  # noqa: F401
                      _parse_document, _split_nhlrc, annotations_for, parse,
                      render, render_body, render_nhlrc)

# 同一首歌的"读-改-写"串行化（HTTP 是多线程的）
LOCK = threading.RLock()


def uid_of(audio: str | Path) -> str:
    """和 library 里一致的 uid：绝对路径的 md5 前 12 位。"""
    return hashlib.md5(str(Path(audio)).encode()).hexdigest()[:12]


def lrc_path(audio: str | Path) -> Path:
    """旧格式：音频旁边的 .lrc（只读兼容，不再写）。"""
    return Path(audio).with_suffix(".lrc")


def nhlrc_path(audio: str | Path) -> Path:
    """旧格式：音频旁边的 .nhlrc（只读兼容，迁移后删除）。"""
    return Path(audio).with_suffix(".nhlrc")


def store_path(uid: str) -> Path:
    return LYRICS / f"{uid}.nhlrc"


def store_backup(uid: str) -> Path:
    return LYRICS / f"{uid}.nhlrc.bak"


def exists(audio: str | Path, uid: str | None = None) -> bool:
    u = uid or uid_of(audio)
    return (store_path(u).is_file() or nhlrc_path(audio).is_file()
            or lrc_path(audio).is_file())


def _migrate_legacy(uid: str, audio: Path) -> Path | None:
    """音频旁有旧 .nhlrc → 复制进 data/lyrics 并删除旧文件。"""
    legacy = nhlrc_path(audio)
    target = store_path(uid)
    if not legacy.is_file() or target.is_file():
        return target if target.is_file() else None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        legacy.unlink()
        diag.log("lyrics", f"迁移旧 nhlrc → {target.name}")
        return target
    except Exception as e:
        diag.log("lyrics", f"迁移旧 nhlrc 失败：{e}")
        return None


def load(audio: str | Path, uid: str | None = None) -> dict:
    """优先 data/lyrics/<uid>.nhlrc，其次旧 .nhlrc，再次 .lrc，最后歌词缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(u)
    lp = lrc_path(audio)
    from_cache = False
    tail = None

    if sp.is_file():
        full = sp.read_text(encoding="utf-8", errors="ignore")
        body, tail = _split_nhlrc(full)
        path, kind = sp, "nhlrc"
    elif nhlrc_path(audio).is_file():
        migrated = _migrate_legacy(u, audio)
        src = migrated or nhlrc_path(audio)
        full = src.read_text(encoding="utf-8", errors="ignore")
        body, tail = _split_nhlrc(full)
        path, kind = src, "nhlrc"
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
        path, kind = sp, "cache"
        from_cache = bool(full)

    # 空壳 nhlrc（正文没有非空行）→ 回退读 .lrc，避免盖住有内容的歌词
    if kind == "nhlrc" and not any((ln.get("text") or "").strip()
                                   for ln in _parse_document(body)[0]) and lp.is_file():
        body = lp.read_text(encoding="utf-8", errors="ignore")
        path, kind, tail = lp, "lrc", None

    lines, metadata = _parse_document(body)
    # 整篇正文哈希一致 → 跳过逐行哈希比对（仍校验下标与拼接）
    strict = not (tail and tail.get("body") and tail["body"] == _hash8(body))
    annotations = annotations_for(lines, tail, strict=strict)
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "text": body, "lines": lines,
            "metadata": metadata, "annotations": annotations,
            "nhlrc": kind == "nhlrc"}


def backup_path(audio: str | Path, uid: str | None = None) -> Path:
    return store_backup(uid or uid_of(audio))


def backup_candidates(audio: str | Path, uid: str | None = None) -> list[Path]:
    u = uid or uid_of(audio)
    a = Path(audio)
    return [store_backup(u), a.with_suffix(".nhlrc.bak"), a.with_suffix(".lrc.bak")]


def backup_status(audio: str | Path, uid: str | None = None) -> dict:
    b = next((x for x in backup_candidates(audio, uid) if x.is_file()), None)
    if not b:
        return {"exists": False}
    text = b.read_text(encoding="utf-8", errors="ignore")
    return {"exists": True, "path": str(b), "lines": len(parse(text)),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def restore_backup(audio: str | Path, uid: str | None = None) -> dict:
    """把备份覆盖回 data/lyrics/<uid>.nhlrc（恢复最初版本），并同步歌词缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    b = next((x for x in backup_candidates(audio, u) if x.is_file()), None)
    if not b:
        return {"ok": False, "error": "没有备份文件"}
    sp = store_path(u)
    sp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b, sp)
    artist, title = LY.split_name(audio.stem)
    body, _ = _split_nhlrc(sp.read_text(encoding="utf-8", errors="ignore"))
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(sp), "lines": len(parse(sp.read_text(encoding="utf-8")))}


def import_text(audio: str | Path, text: str, uid: str | None = None) -> dict:
    """用外部歌词文本覆盖当前歌词：写 data/lyrics/<uid>.nhlrc 的正文。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(u)
    sp.parent.mkdir(parents=True, exist_ok=True)
    backed = False
    bak = store_backup(u)
    src = sp if sp.is_file() else (nhlrc_path(audio) if nhlrc_path(audio).is_file()
                                   else lrc_path(audio))
    if src.is_file() and not bak.exists():
        shutil.copy2(src, bak)
        backed = True
    body, _tail = _split_nhlrc(text)          # 选到 .nhlrc 时只取正文
    body = body if body.endswith("\n") else body + "\n"
    sp.write_text(body, encoding="utf-8")
    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, body,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(sp), "lines": len(parse(body)), "backed_up": backed}


def save(audio: str | Path, lines: list[dict],
         annotations: dict[int, list] | None = None,
         uid: str | None = None) -> dict:
    """写 data/lyrics/<uid>.nhlrc（正文 + 尾部），首次备份成 .nhlrc.bak。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(u)
    sp.parent.mkdir(parents=True, exist_ok=True)

    artist, title = LY.split_name(audio.stem)
    original = ""
    backed = False
    src = sp if sp.is_file() else (nhlrc_path(audio) if nhlrc_path(audio).is_file()
                                   else lrc_path(audio))
    if src.is_file():
        original = src.read_text(encoding="utf-8", errors="ignore")
        bak = store_backup(u)
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
