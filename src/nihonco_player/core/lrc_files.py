#!/usr/bin/env python3
"""LRC / nhlrc 文件层：路径、读写、备份、恢复、与歌词缓存同步。

标注文件统一放在 data/lyrics/<歌名> - <歌手>.<指纹>.nhlrc（不进音乐目录）。
身份只用音频指纹。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
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
VERSION_NONE = "none"


def uid_of(audio: str | Path) -> str:
    """和 library 里一致的 uid：音频指纹（读不了文件时退回路径哈希）。"""
    return FP.fingerprint(audio)


BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME_BYTES = 120


def _version(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _atomic_write(path: Path, text: str) -> None:
    """同目录临时文件 + os.replace；避免半写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _is_disabled_text(text: str) -> bool:
    _body, tail = _split_nhlrc(text)
    return bool(tail and tail.get("disabled"))


def _backup_once(sp: Path, bak: Path) -> bool:
    if sp.is_file() and not bak.exists():
        text = sp.read_text(encoding="utf-8", errors="ignore")
        if _is_disabled_text(text):       # disabled 不是可恢复的歌词备份
            return False
        bak.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, bak)
        return True
    return False


def _disabled_text() -> str:
    return (NHLRC_MARK + f" {NHLRC_VERSION}\n" +
            json.dumps({"v": NHLRC_VERSION, "gen": GEN, "disabled": True},
                       ensure_ascii=False, indent=1) + "\n")


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
    bak_dir = LYRICS / "bak"
    for p in bak_dir.glob(f"*.{u}.nhlrc.bak"):
        return p
    return bak_dir / (store_path(audio, u, title, artist).name + ".bak")


def exists(audio: str | Path, uid: str | None = None) -> bool:
    return store_path(audio, uid or uid_of(audio)).is_file()


def store_index(uids=None) -> dict[str, bool]:
    """nhlrc 是否有非空正文；只查给定 uid 时按 uid glob。"""
    out: dict[str, bool] = {}
    if uids is not None:
        wanted = {str(u) for u in uids}
        for u in wanted:
            for p in LYRICS.glob(f"*.{u}.nhlrc"):
                try:
                    body, _ = _split_nhlrc(p.read_text(encoding="utf-8", errors="ignore"))
                    out[u] = any((r.get("text") or "").strip() for r in parse(body))
                except Exception:
                    out[u] = False
                if out.get(u):
                    break
        return out
    for p in LYRICS.glob("*.nhlrc"):
        u = p.name.rsplit(".", 2)[-2]
        try:
            body, _ = _split_nhlrc(p.read_text(encoding="utf-8", errors="ignore"))
            out[u] = out.get(u, False) or any(
                (r.get("text") or "").strip() for r in parse(body))
        except Exception:
            out.setdefault(u, False)
    return out


def store_has_text(uid: str) -> bool:
    return store_index({uid}).get(str(uid), False)


def usable_doc(doc: dict) -> bool:
    """统一的“有没有可用歌词”判断。"""
    if doc.get("disabled"):
        return False
    lines = doc.get("lines") or []
    if not any((ln.get("text") or "").strip() for ln in lines):
        return False
    allow_untimed = doc.get("kind") == "nhlrc" or doc.get("source") == "local-lrc"
    return allow_untimed or LY.has_timed(doc.get("text") or "")


def load(audio: str | Path, uid: str | None = None,
         title: str | None = None, artist: str | None = None,
         network: bool = False) -> dict:
    """有 nhlrc 就只读 nhlrc（含 disabled）；没有才回退网络缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    from_cache = False
    tail = None
    disabled = False
    version = VERSION_NONE

    if sp.is_file():
        full = sp.read_text(encoding="utf-8", errors="ignore")
        body, tail = _split_nhlrc(full)
        disabled = bool(tail and tail.get("disabled"))
        version = _version(full)
        path, kind, source = sp, "nhlrc", "nhlrc"
    else:
        artist, title = LY.split_name(audio.stem)
        hit = LY.get_lrc(title, artist, network=network) or {}
        full = hit.get("lrc") or ""
        source = hit.get("source") or ""
        cached_ann = hit.get("nhlrc_annotations") or {}
        tail = {"lines": [{"i": int(i), "seg": seg} for i, seg in cached_ann.items()]} \
            if cached_ann else None
        body = full
        path, kind = sp, "cache"
        from_cache = bool(full)

    if disabled:
        return {"ok": True, "exists": True, "from_cache": False,
                "path": str(path), "kind": "nhlrc", "source": "disabled",
                "text": "", "lines": [], "metadata": [],
                "annotations": {}, "nhlrc": True, "disabled": True,
                "version": version}

    lines, metadata = _parse_document(body)
    # 整篇正文哈希一致 → 跳过逐行哈希比对（仍校验下标与拼接）
    strict = not (tail and tail.get("body") and tail["body"] == _hash8(body))
    annotations = annotations_for(lines, tail, strict=strict)
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "source": source, "text": body,
            "lines": lines, "metadata": metadata, "annotations": annotations,
            "nhlrc": kind == "nhlrc", "disabled": False, "version": version}


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
    if _is_disabled_text(text):
        return {"exists": False, "disabled": True}
    return {"exists": True, "path": str(b), "lines": len(parse(text)),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def restore_backup(audio: str | Path, uid: str | None = None,
                   title: str | None = None, artist: str | None = None,
                   expected_version: str | None = None) -> dict:
    """用备份原子恢复权威文档；恢复成功即重新启用歌词。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    with LOCK:
        b = next((x for x in backup_candidates(audio, u, title, artist) if x.is_file()), None)
        if not b:
            return {"ok": False, "error": "没有备份文件"}
        sp = store_path(audio, u, title, artist)
        current = sp.read_text(encoding="utf-8", errors="ignore") if sp.is_file() else ""
        current_version = _version(current) if sp.is_file() else VERSION_NONE
        if expected_version is not None and current_version != str(expected_version):
            return {"ok": False, "conflict": True, "error": "歌词已更新，请重新加载",
                    "version": current_version}
        text = b.read_text(encoding="utf-8", errors="ignore")
        if _is_disabled_text(text):
            return {"ok": False, "error": "没有可恢复的歌词备份"}
        _atomic_write(sp, text)
        return {"ok": True, "path": str(sp), "lines": len(parse(text)),
                "version": _version(text)}


def delete_store(audio: str | Path, uid: str | None = None,
                 title: str | None = None, artist: str | None = None,
                 expected_version: str | None = None) -> dict:
    """把“不要歌词”写成权威 disabled 文档；保留备份，便于恢复。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK:
        current = sp.read_text(encoding="utf-8", errors="ignore") if sp.is_file() else ""
        current_version = _version(current) if sp.is_file() else VERSION_NONE
        if expected_version is not None and current_version != str(expected_version):
            return {"ok": False, "conflict": True, "error": "歌词已更新，请重新加载",
                    "version": current_version}
        if sp.is_file():
            _backup_once(sp, bak)
        text = _disabled_text()
        _atomic_write(sp, text)
        return {"ok": True, "disabled": True, "path": str(sp),
                "version": _version(text), "backed_up": bak.is_file()}


def import_text(audio: str | Path, text: str, uid: str | None = None,
                title: str | None = None, artist: str | None = None,
                expected_version: str | None = None) -> dict:
    """用户导入：直接原子写权威 nhlrc，不写共享缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK:
        current = sp.read_text(encoding="utf-8", errors="ignore") if sp.is_file() else ""
        current_version = _version(current) if sp.is_file() else VERSION_NONE
        if expected_version is not None and current_version != str(expected_version):
            return {"ok": False, "conflict": True, "error": "歌词已更新，请重新加载",
                    "version": current_version}
        backed = _backup_once(sp, bak)
        body, tail = _split_nhlrc(text)
        body = body if body.endswith("\n") else body + "\n"
        lines, metadata = _parse_document(body)
        annotations = annotations_for(lines, tail) if tail else {}
        out = render_nhlrc(lines, metadata, annotations) if annotations else body
        _atomic_write(sp, out)
        return {"ok": True, "path": str(sp), "lines": len(lines),
                "annotated": len(annotations), "backed_up": backed,
                "version": _version(out)}


def save(audio: str | Path, lines: list[dict],
         annotations: dict[int, list] | None = None,
         uid: str | None = None,
         title: str | None = None, artist: str | None = None,
         expected_version: str | None = None) -> dict:
    """写权威 nhlrc；锁内校验版本、备份并原子替换。不写共享缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK:
        original = sp.read_text(encoding="utf-8", errors="ignore") if sp.is_file() else ""
        current_version = _version(original) if sp.is_file() else VERSION_NONE
        if expected_version is not None and current_version != str(expected_version):
            return {"ok": False, "conflict": True, "error": "歌词已更新，请重新加载",
                    "version": current_version}
        backed = _backup_once(sp, bak)
        body, _tail = _split_nhlrc(original)
        _, metadata = _parse_document(body)
        if annotations is None:
            annotations = annotations_for(lines, _tail)
        text = render_nhlrc(lines, metadata, annotations)
        _atomic_write(sp, text)
        return {"ok": True, "path": str(sp), "lines": len(lines),
                "backed_up": backed, "version": _version(text)}
