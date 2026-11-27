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
import time
from pathlib import Path

from momo_yomi.paths import LYRICS

from . import diag
from . import fsio as FS
from . import fingerprint as FP
from . import lyrics as LY
from .lyric_rows import parse_rows as parse_v2_rows, render_rows as render_v2_rows
from .lrc_doc import (NHLRC_MARK, GEN, _parse_document, _parse_rows,
                      _split_nhlrc, parse, new_line_id, new_token_ids,
                      tokens_with_spans, translations_from_lrc,
                      is_metadata_text)

# 同一首歌的"读-改-写"串行化（HTTP 是多线程的）
LOCK = threading.RLock()
VERSION_NONE = "none"


def uid_of(audio: str | Path) -> str:
    """和 library 里一致的 uid：音频指纹（读不了文件时退回路径哈希）。"""
    return FP.fingerprint(audio)


BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_NAME_BYTES = int(LY.CFG.get("max_name_bytes", 120) or 120)


def _version(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _atomic_write(path: Path, text: str) -> None:
    FS.atomic_write_text(path, text)


def _read_original(path: Path) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    text = path.read_text(encoding="utf-8", errors="ignore")
    # 0 字节/纯空白文件视为不存在，否则版本是 sha1("")，会永久 409。
    return (text, True) if text.strip() else ("", False)


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


def _has_document_content(rows: list[dict]) -> bool:
    return any(row.get("kind") in ("lyric", "metadata")
               and (row.get("text") or "").strip() for row in rows)


def _row_ids(rows: list[dict]) -> list[dict]:
    """保存后回传行身份，供前端合并服务端生成的 lid/tid。"""
    return [{"i": i, "text": row.get("text") or "", "lid": row.get("lid"),
             "tokens": row.get("tokens") or []}
            for i, row in enumerate(rows) if row.get("kind") == "lyric"]


def lock_path() -> Path:
    return LYRICS / ".lock"


def _is_disabled_text(text: str) -> bool:
    _body, tail = _split_nhlrc(text)
    return bool(tail and tail.get("disabled"))


SNAPSHOT_KEEP = 5


def _snapshot(sp: Path) -> Path | None:
    """破坏性覆盖前保存带时间戳的快照；disabled 不是可恢复内容。"""
    if not sp.is_file():
        return None
    text = sp.read_text(encoding="utf-8", errors="ignore")
    if _is_disabled_text(text):
        return None
    bak_dir = sp.parent / "bak"
    bak_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    out = bak_dir / f"{sp.name}.{stamp}.bak"
    shutil.copy2(sp, out)
    snapshots = sorted(bak_dir.glob(f"{sp.name}.*.bak"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snapshots[SNAPSHOT_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return out


def _backup_once(sp: Path, bak: Path) -> bool:
    if sp.is_file() and not bak.exists():
        text = sp.read_text(encoding="utf-8", errors="ignore")
        if not text.strip() or _is_disabled_text(text):
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


def is_no_lyric_document(text: str) -> bool:
    """V2 文档合法但没有 lyric 行：明确无歌词，不是空文件。"""
    _body, tail = _split_nhlrc(text)
    if tail is None or tail.get("v") != 2:
        return False
    try:
        rows = parse_v2_rows(text)
    except Exception:
        return False
    return not any(row.get("kind") == "lyric"
                   and (row.get("text") or "").strip() for row in rows)


def _has_lyric_text(full: str, body: str, tail: dict | None) -> bool:
    """V2 只数 lyric 行；plain/legacy 用旧正文扫描。"""
    if tail and tail.get("v") == 2:
        try:
            return any(row.get("kind") == "lyric"
                       and (row.get("text") or "").strip()
                       for row in parse_v2_rows(full))
        except Exception:
            return False
    return any((r.get("text") or "").strip() for r in _parse_rows(body)[0])


def store_index(uids=None) -> dict[str, bool]:
    """nhlrc 是否有非空正文；只查给定 uid 时按 uid glob。"""
    out: dict[str, bool] = {}
    if uids is not None:
        wanted = {str(u) for u in uids}
        for u in wanted:
            for p in LYRICS.glob(f"*.{u}.nhlrc"):
                try:
                    full = p.read_text(encoding="utf-8", errors="ignore")
                    body, tail = _split_nhlrc(full)
                    has_text = _has_lyric_text(full, body, tail)
                    if tail and tail.get("disabled"):
                        out[u] = False
                    elif tail is not None:
                        # 有 NHLRC 结构但没歌词行：这是权威的空文档，不读缓存。
                        out[u] = out.get(u, False) or has_text
                    elif has_text:
                        out[u] = True
                    # 纯空文件（没有 NHLRC 结构）不写 key，让缓存继续可用。
                except Exception:
                    out[u] = False
                if out.get(u):
                    break
        return out
    for p in LYRICS.glob("*.nhlrc"):
        u = p.name.rsplit(".", 2)[-2]
        try:
            full = p.read_text(encoding="utf-8", errors="ignore")
            body, tail = _split_nhlrc(full)
            has_text = _has_lyric_text(full, body, tail)
            if tail and tail.get("disabled"):
                out[u] = False
            elif tail is not None:
                # 有 NHLRC 结构但没歌词行：这是权威的空文档，不读缓存。
                out[u] = out.get(u, False) or has_text
            elif has_text:
                out[u] = True
            # 纯空文件（没有 NHLRC 结构）不写 key，让缓存继续可用。
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
                      source: str = "nhlrc", trans_lang: str = "zh") -> dict:
    """把 v2 rows 投影成旧 reader 需要的字段，供保存/兼容路径使用。"""
    body_rows, lines, metadata = [], [], []
    annotations, line_ids, token_ids, translations = {}, {}, {}, {}
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
                  path: str = "", source: str = "nhlrc",
                  trans_lang: str = "zh") -> dict:
    return _doc_from_v2_rows(rows, Path(path), version, source, trans_lang)


def load(audio: str | Path, uid: str | None = None,
         title: str | None = None, artist: str | None = None,
         network: bool = False) -> dict:
    """读本地 V2 nhlrc；空文件/坏文件回退网络缓存，disabled 直接返回。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    from_cache = False
    full = ""
    body = ""
    hit = {}
    tail = None
    disabled = False
    version = VERSION_NONE
    path: Path = sp
    kind = "cache"
    source = ""

    if sp.is_file():
        full = sp.read_text(encoding="utf-8", errors="ignore")
        if full.strip():
            body, tail = _split_nhlrc(full)
            disabled = bool(tail and tail.get("disabled"))
            version = _version(full)
            path, kind, source = sp, "nhlrc", "nhlrc"
        else:
            full = ""

    if tail and tail.get("v") == 2 and not disabled:
        try:
            rows = parse_v2_rows(full)
            return _doc_from_v2_rows(rows, path, version, source,
                                     (tail.get("trans_lang") or "zh"))
        except Exception as e:
            # 坏 V2 不阻塞播放：按没有本地 nhlrc 处理，回退缓存。
            diag.log("lrc", f"nhlrc 解析失败，回退缓存：{sp}：{e}")
            full = ""
            body = ""
            tail = None
            version = VERSION_NONE
            kind, source = "cache", ""

    if not full.strip():
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
    if tail and tail.get("v") != 2:
        return {"ok": False, "error": "不支持的 nhlrc 版本", "exists": True,
                "path": str(path), "lines": [], "body_rows": [],
                "metadata": [], "annotations": {}, "line_ids": {},
                "token_ids": {}, "translations": {}, "disabled": False,
                "version": version}

    lines, metadata, body_rows = _parse_rows(body)
    translations = (translations_from_lrc((hit or {}).get("tlyric") or "", lines)
                    if from_cache else {})
    return {"ok": True, "exists": kind != "cache", "from_cache": from_cache,
            "path": str(path), "kind": kind, "source": source, "text": body,
            "lines": lines, "body_rows": body_rows, "metadata": metadata,
            "annotations": {}, "line_ids": {}, "token_ids": {},
            "translations": translations,
            "trans_lang": "zh",
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
    out = []
    for row in skeleton:
        if row.get("kind") == "metadata":
            out.append(row)
            continue
        if bi >= len(body):
            continue                      # 编辑器删掉的行：旧骨架不再保留
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
        out.append(row)
        bi += 1
    # 编辑器可能比旧正文多出行：追加到末尾，不能因为骨架短就静默丢弃。
    while bi < len(body):
        ln = body[bi]
        text = str(ln.get("text") or "")
        if not text.strip():
            out.append({"kind": "blank", "text": "", "t": ln.get("t")})
        else:
            lid = lids.get(lyric) or new_line_id()
            seg = ann.get(lyric) or []
            ids = tids.get(lyric) or new_token_ids(len(seg))
            out.append({
                "kind": "lyric", "text": text, "t": ln.get("t"), "lid": lid,
                "tokens": tokens_with_spans(seg, ids, text) if seg else [],
                "trans": str(ln.get("trans") or trans.get(lyric) or "")})
            lyric += 1
        bi += 1
    return out


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
    """读 rows；只接受 v2 nhlrc。"""
    audio = Path(audio)
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    if not sp.is_file():
        return {"ok": True, "rows": [], "version": VERSION_NONE, "exists": False}
    full = sp.read_text(encoding="utf-8", errors="ignore")
    if not full.strip():
        return {"ok": True, "rows": [], "version": VERSION_NONE, "exists": False}
    _body, tail = _split_v2_tail(full)
    if tail and tail.get("disabled"):
        return {"ok": True, "rows": [], "version": _version(full),
                "exists": True, "model": 0, "disabled": True,
                "trans_lang": "zh"}
    if not tail or tail.get("v") != 2:
        return {"ok": False, "error": "不支持的 nhlrc 版本", "rows": []}
    try:
        rows = parse_v2_rows(full)
    except ValueError as e:
        return {"ok": False, "error": str(e), "rows": []}
    return {"ok": True, "rows": rows, "version": _version(full),
            "exists": True, "model": 2,
            "trans_lang": tail.get("trans_lang") or "zh"}


def save_rows(audio: str | Path, rows: list[dict],
              uid: str | None = None, title: str | None = None,
              artist: str | None = None, expected_version: str | None = None,
              trans_lang: str | None = None) -> dict:
    """写 v2 rows；版本校验、首次备份、原子替换。"""
    if not rows:
        return {"ok": False, "error": "没有歌词行"}
    if not _has_document_content(rows):
        return {"ok": True, "skipped": True, "rows": 0, "ids": [],
                "backed_up": False}
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
        _annotate_missing_tokens(rows)
        text, backed = _write_v2(sp, bak, rows, trans_lang)
        return {"ok": True, "path": str(sp), "rows": len(rows),
                "ids": _row_ids(rows),
                "backed_up": backed, "version": _version(text)}


def current_version(audio: str | Path, uid: str | None = None,
                    title: str | None = None, artist: str | None = None) -> str | None:
    """返回当前 nhlrc 版本；不存在或为空时返回 None。"""
    sp = store_path(audio, uid, title, artist)
    text, exists = _read_original(sp)
    return _version(text) if exists else None


def backup_candidates(audio: str | Path, uid: str | None = None,
                      title: str | None = None, artist: str | None = None) -> list[Path]:
    u = uid or uid_of(audio)
    sp = store_path(audio, u, title, artist)
    snaps = sorted((sp.parent / "bak").glob(f"{sp.name}.*.bak"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    original = store_backup(audio, u, title, artist)
    return snaps + ([original] if original.is_file() else [])


def _backup_lines(text: str) -> int:
    try:
        rows = parse_v2_rows(text)
    except Exception:
        body, _tail = _split_nhlrc(text)
        return len(parse(body))
    return sum(1 for r in rows
               if r.get("kind") == "lyric" and (r.get("text") or "").strip())


def backup_status(audio: str | Path, uid: str | None = None,
                  title: str | None = None, artist: str | None = None) -> dict:
    b = next((x for x in backup_candidates(audio, uid, title, artist) if x.is_file()), None)
    if not b:
        return {"exists": False}
    text = b.read_text(encoding="utf-8", errors="ignore")
    if _is_disabled_text(text):
        return {"exists": False, "disabled": True}
    return {"exists": True, "path": str(b), "lines": _backup_lines(text),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def _annotate_missing_tokens(rows: list[dict]) -> None:
    """普通 LRC 没有读音尾部；导入时按正文生成一次 token。"""
    from .annotation import annotate_line_with_notes, segs_of
    for row in rows:
        if row.get("kind") != "lyric" or row.get("tokens"):
            continue
        text = row.get("text") or ""
        try:
            result = annotate_line_with_notes(text)
            segs = segs_of(result)
            row["tokens"] = tokens_with_spans(segs, new_token_ids(len(segs)), text)
        except Exception:
            continue


def plain_lrc_rows(text: str) -> list[dict]:
    """外部普通 LRC → v2 rows；不读取任何 nhlrc 尾部。"""
    body, _tail = _split_nhlrc(text)
    _lines, metadata, body_rows = _parse_rows(body)
    # 网易云等来源会带“空文本 + 时间倒序”的占位行；只清这一类，
    # 保留有序空行、无时间空行和 metadata。
    cleaned = []
    last_t = None
    for row in body_rows:
        t = row.get("t")
        empty = not str(row.get("text") or "").strip()
        if t is not None and empty and last_t is not None and t < last_t:
            continue
        cleaned.append(row)
        if t is not None:
            last_t = t
    body_rows = cleaned
    body_to_lyric = {}
    lyric = 0
    for bi, ln in enumerate(body_rows):
        if (ln.get("text") or "").strip():
            body_to_lyric[bi] = lyric
            lyric += 1
    meta_body = _metadata_for_body(metadata, body_to_lyric, len(body_rows))
    rows = _rows_from_body(body_rows, meta_body, {}, {}, {}, {}, body_to_lyric)
    _annotate_missing_tokens(rows)
    return rows


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
        _snapshot(sp)
        text = b.read_text(encoding="utf-8", errors="ignore")
        if _is_disabled_text(text):
            return {"ok": False, "error": "没有可恢复的歌词备份"}
        try:
            parse_v2_rows(text)
        except ValueError:
            return {"ok": False, "error": "不支持的 nhlrc 版本"}
        _atomic_write(sp, text)
        return {"ok": True, "path": str(sp), "lines": _backup_lines(text),
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
        _snapshot(sp)
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
    if tail and tail.get("v") != 2:
        return False, "不支持的 nhlrc 版本"
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
        _snapshot(sp)
        body, tail = _split_nhlrc(text)
        if tail and tail.get("v") != 2:
            return {"ok": False, "error": "不支持的 nhlrc 版本"}
        if tail and tail.get("disabled"):
            out = _disabled_text()
            backed = _backup_once(sp, bak)
            _atomic_write(sp, out)
            return {"ok": True, "disabled": True, "path": str(sp),
                    "lines": 0, "annotated": 0, "backed_up": backed,
                    "version": _version(out)}
        try:
            rows = parse_v2_rows(text) if tail else plain_lrc_rows(text)
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
        if is_metadata_text(text):
            rows.append({"kind": "metadata", "text": text, "t": ln.get("t")})
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
    if not lines and not metadata:
        return {"ok": False, "error": "没有歌词行"}
    if not any((ln.get("text") or "").strip() for ln in (lines or [])) and not metadata:
        return {"ok": True, "skipped": True, "rows": 0, "ids": [],
                "backed_up": False}
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
            annotations = {}
        if translations is None:
            translations = {}
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
