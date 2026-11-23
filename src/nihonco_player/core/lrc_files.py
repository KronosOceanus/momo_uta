#!/usr/bin/env python3
"""LRC / nhlrc 文件层：路径、读写、备份、恢复、与歌词缓存同步。

标注文件统一放在 data/lyrics/<歌名> - <歌手>.<指纹>.nhlrc（不进音乐目录）。
身份只用音频指纹。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from pathlib import Path

from nihonco_yomi.paths import LYRICS

from . import fsio as FS
from . import fingerprint as FP
from . import lyrics as LY
from .lyric_rows import parse_rows as parse_v2_rows, render_rows as render_v2_rows
from .lrc_doc import (NHLRC_MARK, GEN, _hash8,  # noqa: F401
                      _parse_document, _parse_rows, _split_nhlrc,
                      annotations_for, annotations_and_ids_for, parse,
                      new_line_id, new_token_ids, tokens_with_spans,
                      translations_for, translations_from_lrc)

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
    FS.atomic_write_text(path, text)


def _read_original(path: Path) -> tuple[str, bool]:
    exists = path.is_file()
    return (path.read_text(encoding="utf-8", errors="ignore") if exists else ""), exists


def _version_conflict(original: str, exists: bool,
                      expected_version: str | None) -> tuple[str, dict | None]:
    current = _version(original) if exists else VERSION_NONE
    if expected_version is not None and current != str(expected_version):
        return current, {"ok": False, "conflict": True,
                         "error": "歌词已更新，请重新加载", "version": current}
    return current, None


def _write_v2(path: Path, backup: Path, rows: list[dict],
              trans_lang: str) -> tuple[str, bool]:
    text = render_v2_rows(rows, trans_lang)
    backed = _backup_once(path, backup)
    _atomic_write(path, text)
    return text, backed


def lock_path() -> Path:
    return LYRICS / ".lock"


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
    return (NHLRC_MARK + " 2\n" +
            json.dumps({"v": 2, "gen": GEN, "disabled": True},
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


def usable_doc(doc: dict) -> bool:
    """统一的“有没有可用歌词”判断。"""
    if doc.get("disabled"):
        return False
    lines = doc.get("lines") or []
    if not any((ln.get("text") or "").strip() for ln in lines):
        return False
    return doc.get("kind") == "nhlrc" or LY.has_timed(doc.get("text") or "")


def _doc_from_v2_rows(rows: list[dict], path: Path, version: str,
                      source: str = "nhlrc") -> dict:
    """把 v2 rows 投影成旧 reader 需要的字段，供保存/兼容路径使用。"""
    body_rows, lines, metadata = [], [], []
    annotations, line_ids, token_ids, translations = {}, {}, {}, {}
    trans_lang = "zh"
    for row in rows:
        kind = row.get("kind")
        if kind == "metadata":
            metadata.append({"before": len(lines), "text": row.get("text") or ""})
            continue
        text = row.get("text") or ""
        body_rows.append({"t": row.get("t"), "text": text})
        if kind != "lyric" or not text.strip():
            continue
        li = len(lines)
        lines.append({"t": row.get("t"), "text": text})
        if row.get("lid"):
            line_ids[li] = row["lid"]
        toks = row.get("tokens") or []
        if toks:
            annotations[li] = [[t.get("base", ""), t.get("ruby"), t.get("level")]
                               for t in toks]
            token_ids[li] = [t.get("tid") for t in toks]
        if row.get("trans"):
            translations[li] = row["trans"]
    return {"ok": True, "exists": True, "from_cache": False,
            "path": str(path), "kind": "nhlrc", "source": source,
            "text": body_text_of(rows), "lines": lines,
            "body_rows": body_rows, "metadata": metadata,
            "annotations": annotations, "line_ids": line_ids,
            "token_ids": token_ids, "translations": translations,
            "trans_lang": trans_lang, "nhlrc": True, "disabled": False,
            "version": version}


def body_text_of(rows: list[dict]) -> str:
    from .lyric_rows import body_text
    return body_text(rows)


def doc_from_rows(rows: list[dict], version: str = VERSION_NONE,
                  path: str = "", source: str = "nhlrc") -> dict:
    return _doc_from_v2_rows(rows, Path(path), version, source)


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
        tail = None
        body = full
        path, kind = sp, "cache"
        from_cache = bool(full)

    if disabled:
        return {"ok": True, "exists": True, "from_cache": False,
                "path": str(path), "kind": "nhlrc", "source": "disabled",
                "text": "", "lines": [], "body_rows": [], "metadata": [],
                "annotations": {}, "line_ids": {}, "token_ids": {},
                "translations": {}, "trans_lang": "zh",
                "nhlrc": True, "disabled": True, "version": version}
    if tail and tail.get("v") == 2:
        rows = parse_v2_rows(full)
        doc = _doc_from_v2_rows(rows, path, version, source)
        doc["trans_lang"] = (tail.get("trans_lang") or "zh")
        return doc

    lines, metadata, body_rows = _parse_rows(body)
    # 整篇正文哈希一致 → 跳过逐行哈希比对（仍校验下标与拼接）
    strict = not (tail and tail.get("body") and tail["body"] == _hash8(body))
    annotations, line_ids, token_ids = annotations_and_ids_for(lines, tail, strict=strict)
    if from_cache:
        translations = translations_from_lrc((hit or {}).get("tlyric") or "", lines)
    else:
        translations = translations_for(lines, tail, strict=strict)
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "source": source, "text": body,
            "lines": lines, "body_rows": body_rows, "metadata": metadata,
            "annotations": annotations,
            "line_ids": line_ids, "token_ids": token_ids,
            "translations": translations,
            "trans_lang": (tail or {}).get("trans_lang") or "zh",
            "nhlrc": kind == "nhlrc", "disabled": False, "version": version}


def _split_v2_tail(text: str) -> tuple[str, dict | None]:
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(NHLRC_MARK):
            try:
                return "\n".join(lines[:i]), json.loads("\n".join(lines[i + 1:]) or "{}")
            except Exception:
                return "\n".join(lines[:i]), None
    return text, None


def rows_from_legacy(doc: dict, lines: list[dict] | None = None) -> list[dict]:
    """旧/缓存文档保留正文里的 metadata 顺序，构造导出用 rows。"""
    skeleton = parse_v2_rows(doc.get("text") or "")
    body = lines if lines is not None else (doc.get("body_rows") or doc.get("lines") or [])
    ann = doc.get("annotations") or {}
    tids = doc.get("token_ids") or {}
    lids = doc.get("line_ids") or {}
    trans = doc.get("translations") or {}
    bi = lyric = 0
    for row in skeleton:
        if row.get("kind") == "metadata":
            continue
        if bi >= len(body):
            continue
        ln = body[bi]
        text = str(ln.get("text") or "")
        row["t"] = ln.get("t")
        row["text"] = text
        row["kind"] = "lyric" if text.strip() else "blank"
        if row["kind"] == "lyric":
            if lids.get(lyric):
                row["lid"] = lids[lyric]
            seg = ann.get(lyric) or []
            row["tokens"] = tokens_with_spans(seg, tids.get(lyric) or [],
                                              text) if seg else []
            row["trans"] = str(ln.get("trans") or trans.get(lyric) or "")
            lyric += 1
        else:
            row["lid"] = None
            row["tokens"] = []
            row["trans"] = ""
        bi += 1
    # 编辑器可能比旧正文多出行：追加到末尾，不能因为骨架短就静默丢弃。
    while bi < len(body):
        ln = body[bi]
        text = str(ln.get("text") or "")
        if not text.strip():
            skeleton.append({"kind": "blank", "text": "", "t": ln.get("t")})
        else:
            lid = lids.get(lyric) or new_line_id()
            seg = ann.get(lyric) or []
            ids = tids.get(lyric) or new_token_ids(len(seg))
            skeleton.append({
                "kind": "lyric", "text": text, "t": ln.get("t"), "lid": lid,
                "tokens": tokens_with_spans(seg, ids, text) if seg else [],
                "trans": str(ln.get("trans") or trans.get(lyric) or "")})
            lyric += 1
        bi += 1
    return skeleton


def export_rows(doc: dict, lines: list[dict] | None = None,
                rows: list[dict] | None = None) -> list[dict]:
    """统一导出入口：调用方给 rows 就用 rows，否则从旧正文/body 构造。"""
    if rows is None and lines and any("kind" in x for x in lines):
        rows, lines = lines, None
    if rows is not None:
        return rows
    body = lines if lines is not None else (doc.get("body_rows") or doc.get("lines") or [])
    return rows_from_legacy(doc, body)


def load_rows(audio: str | Path, uid: str | None = None,
              title: str | None = None, artist: str | None = None) -> dict:
    """读 rows；没有文件返回空 rows，v1 在内存转成 rows。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    if not sp.is_file():
        return {"ok": True, "rows": [], "version": VERSION_NONE, "exists": False}
    full = sp.read_text(encoding="utf-8", errors="ignore")
    _body, tail = _split_v2_tail(full)
    if tail and tail.get("disabled"):
        return {"ok": True, "rows": [], "version": _version(full),
                "exists": True, "model": 0, "disabled": True,
                "trans_lang": "zh"}
    model = 2 if tail and tail.get("v") == 2 else 0
    try:
        rows = parse_v2_rows(full if model == 2 else to_v2_text(full))
    except ValueError as e:
        return {"ok": False, "error": str(e), "rows": []}
    return {"ok": True, "rows": rows, "version": _version(full),
            "exists": True, "model": 2,
            "trans_lang": (tail or {}).get("trans_lang") or "zh"}


def save_rows(audio: str | Path, rows: list[dict],
              uid: str | None = None, title: str | None = None,
              artist: str | None = None, expected_version: str | None = None,
              trans_lang: str | None = None) -> dict:
    """写 v2 rows；版本校验、首次备份、原子替换。"""
    if not rows:
        return {"ok": False, "error": "没有歌词行"}
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK, FS.locked(lock_path()):
        original, exists = _read_original(sp)
        _, conflict = _version_conflict(original, exists, expected_version)
        if conflict:
            return conflict
        if trans_lang is None:
            _body, tail = _split_v2_tail(original)
            trans_lang = (tail or {}).get("trans_lang") or "zh"
        text, backed = _write_v2(sp, bak, rows, trans_lang)
        return {"ok": True, "path": str(sp), "rows": len(rows),
                "backed_up": backed, "version": _version(text)}


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


def to_v2_text(text: str) -> str:
    """把旧 v1 文档转成 v2；普通读取不拒绝 v1，恢复备份时统一写 v2。"""
    body, tail = _split_nhlrc(text)
    if tail and tail.get("v") == 2:
        return text
    if tail and tail.get("disabled"):
        return _disabled_text()
    lines, metadata, body_rows = _parse_rows(body)
    body_to_lyric = {}
    lyric = 0
    for bi, ln in enumerate(body_rows):
        if (ln.get("text") or "").strip():
            body_to_lyric[bi] = lyric
            lyric += 1
    annotations, line_ids, token_ids = (annotations_and_ids_for(lines, tail)
                                         if tail else ({}, {}, {}))
    translations = translations_for(lines, tail) if tail else {}
    ann_body = {bi: annotations[li] for bi, li in body_to_lyric.items()
                if li in annotations}
    trans_body = {bi: translations[li] for bi, li in body_to_lyric.items()
                  if li in translations}
    lids_body = {bi: line_ids[li] for bi, li in body_to_lyric.items()
                 if li in line_ids}
    tids_body = {bi: token_ids[li] for bi, li in body_to_lyric.items()
                 if li in token_ids}
    meta_body = _metadata_for_body(metadata, body_to_lyric, len(body_rows))
    rows = _rows_from_body(body_rows, meta_body, ann_body, trans_body,
                           lids_body, tids_body, body_to_lyric)
    return render_v2_rows(rows, (tail or {}).get("trans_lang") or "zh")


def restore_backup(audio: str | Path, uid: str | None = None,
                   title: str | None = None, artist: str | None = None,
                   expected_version: str | None = None) -> dict:
    """用备份原子恢复权威文档；恢复成功即重新启用歌词。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    with LOCK, FS.locked(lock_path()):
        b = next((x for x in backup_candidates(audio, u, title, artist) if x.is_file()), None)
        if not b:
            return {"ok": False, "error": "没有备份文件"}
        sp = store_path(audio, u, title, artist)
        original, exists = _read_original(sp)
        _, conflict = _version_conflict(original, exists, expected_version)
        if conflict:
            return conflict
        text = b.read_text(encoding="utf-8", errors="ignore")
        if _is_disabled_text(text):
            return {"ok": False, "error": "没有可恢复的歌词备份"}
        text = to_v2_text(text)
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
    with LOCK, FS.locked(lock_path()):
        original, exists = _read_original(sp)
        _, conflict = _version_conflict(original, exists, expected_version)
        if conflict:
            return conflict
        if sp.is_file():
            _backup_once(sp, bak)
        text = _disabled_text()
        _atomic_write(sp, text)
        return {"ok": True, "disabled": True, "path": str(sp),
                "version": _version(text), "backed_up": bak.is_file()}


def valid_import(text: str) -> tuple[bool, str]:
    """导入前的统一校验：空、乱码、或普通 LRC 的有效行数不足都拒绝。

    带读音/翻译尾部的 nhlrc 允许少于普通 LRC 行数，因为它是已整理文档。
    """
    text = str(text or "")
    if not text.strip():
        return False, "文件是空的"
    if "\ufffd" in text:
        return False, "文件不是有效的 UTF-8 文本"
    body, tail = _split_nhlrc(text)
    if tail and tail.get("disabled"):
        return True, ""
    if tail and (tail.get("lines") or tail.get("trans")):
        return True, ""
    n = LY.content_lines(body)
    if n < int(LY.CFG["min_content_lines"]):
        return False, f"有效歌词不足 {LY.CFG['min_content_lines']} 行"
    return True, ""


def import_text(audio: str | Path, text: str, uid: str | None = None,
                title: str | None = None, artist: str | None = None,
                expected_version: str | None = None,
                translations: dict[int, str] | None = None,
                trans_lang: str | None = None) -> dict:
    """用户导入：直接原子写权威 v2 nhlrc，不写共享缓存。"""
    ok, why = valid_import(text)
    if not ok:
        return {"ok": False, "error": why}
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK, FS.locked(lock_path()):
        original, exists = _read_original(sp)
        _, conflict = _version_conflict(original, exists, expected_version)
        if conflict:
            return conflict
        body, tail = _split_nhlrc(text)
        if tail and tail.get("disabled"):
            out = _disabled_text()
            backed = _backup_once(sp, bak)
            _atomic_write(sp, out)
            return {"ok": True, "disabled": True, "path": str(sp),
                    "lines": 0, "annotated": 0, "backed_up": backed,
                    "version": _version(out)}
        try:
            rows = parse_v2_rows(to_v2_text(text))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        lyric_rows = [row for row in rows if row.get("kind") == "lyric"]
        for i, row in enumerate(lyric_rows):
            if translations is not None and i in translations:
                row["trans"] = str(translations[i] or "")
        out, backed = _write_v2(sp, bak, rows,
                                trans_lang or (tail or {}).get("trans_lang") or "zh")
        return {"ok": True, "path": str(sp), "lines": len(lyric_rows),
                "annotated": sum(1 for row in lyric_rows if row.get("tokens")),
                "backed_up": backed, "version": _version(out)}


def _metadata_for_body(metadata, annotation_index, body_len):
    """把 compact 行前的 metadata 位置映射到 body 行前。"""
    tags = list(metadata or ())
    if not tags:
        return []
    by_lyric = {int(li): int(bi) for bi, li in (annotation_index or {}).items()}
    lyric_count = len(by_lyric)
    out = []
    for tag in tags:
        try:
            before = int(tag.get("before", 0))
        except (TypeError, ValueError):
            before = 0
        if before <= 0:
            body_before = 0
        elif before >= lyric_count:
            body_before = body_len
        else:
            body_before = by_lyric.get(before, body_len)
        out.append({"before": body_before, "text": tag.get("text", "")})
    return out


def _rows_from_body(lines, metadata, annotations, translations,
                    line_ids, token_ids, annotation_index) -> list[dict]:
    """旧 body/compact 入参 → v2 rows；供旧保存入口一次性转换。"""
    by_before = {}
    for tag in metadata or []:
        try:
            before = int(tag.get("before", 0))
        except (TypeError, ValueError):
            before = 0
        by_before.setdefault(before, []).append(tag)
    rows = []
    for bi, ln in enumerate(lines or []):
        for tag in by_before.pop(bi, []):
            rows.append({"kind": "metadata", "text": tag.get("text", ""), "t": None})
        text = str(ln.get("text") or "")
        if not text.strip():
            rows.append({"kind": "blank", "text": "", "t": ln.get("t")})
            continue
        lid = (line_ids or {}).get(bi) or new_line_id()
        seg = (annotations or {}).get(bi) or []
        tids = (token_ids or {}).get(bi) or new_token_ids(len(seg))
        tokens = tokens_with_spans(seg, tids, text)
        rows.append({"kind": "lyric", "text": text, "t": ln.get("t"),
                     "lid": lid, "tokens": tokens,
                     "trans": (translations or {}).get(bi) or ""})
    for before in sorted(by_before):
        for tag in by_before[before]:
            rows.append({"kind": "metadata", "text": tag.get("text", ""), "t": None})
    return rows


def save(audio: str | Path, lines: list[dict],
         annotations: dict[int, list] | None = None,
         translations: dict[int, str] | None = None,
         uid: str | None = None,
         title: str | None = None, artist: str | None = None,
         expected_version: str | None = None, trans_lang: str | None = None,
         line_ids: dict[int, str] | None = None,
         token_ids: dict[int, list[str]] | None = None,
         annotation_index: dict[int, int] | None = None,
         metadata: list[dict] | None = None) -> dict:
    """写权威 nhlrc；锁内校验版本、备份并原子替换。不写共享缓存。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    bak = store_backup(audio, u, title, artist)
    with LOCK, FS.locked(lock_path()):
        original, exists = _read_original(sp)
        _, conflict = _version_conflict(original, exists, expected_version)
        if conflict:
            return conflict
        body, _tail = _split_nhlrc(original)
        if trans_lang is None:
            trans_lang = (_tail or {}).get("trans_lang") or "zh"
        if metadata is None:
            _, metadata = _parse_document(body)
        if annotations is None:
            annotations = annotations_for(lines, _tail)
        if translations is None:
            translations = translations_for(lines, _tail)
        if annotation_index is None:
            annotation_index = {}
            lyric = 0
            for bi, ln in enumerate(lines):
                if (ln.get("text") or "").strip():
                    annotation_index[bi] = lyric
                    lyric += 1
        body_meta = _metadata_for_body(metadata, annotation_index, len(lines))
        rows = _rows_from_body(lines, body_meta, annotations, translations,
                               line_ids, token_ids, annotation_index)
        text, backed = _write_v2(sp, bak, rows, trans_lang)
        return {"ok": True, "path": str(sp), "lines": len(lines),
                "backed_up": backed, "version": _version(text)}
