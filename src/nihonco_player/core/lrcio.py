#!/usr/bin/env python3
"""读写 .lrc：解析、生成、备份、与歌词缓存同步。

编辑行保留无时间戳的文本。文件元数据独立保留。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from . import lyrics as LY

NHLRC_MARK = "#NHLRC"
NHLRC_VERSION = 1
GEN = "nihonco 0.1"

LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)(?:-\d+)?\](.*)$")
METADATA = re.compile(
    r"(?:\[(?:ar|al|ti|au|by|offset|length|re|ve|la|id|tool):[^\]\r\n]*\][ \t]*)+",
    re.IGNORECASE,
)


def lrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".lrc")


def nhlrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".nhlrc")


def exists(audio: str | Path) -> bool:
    return nhlrc_path(audio).is_file() or lrc_path(audio).is_file()


def _hash8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _split_nhlrc(text: str) -> tuple[str, dict | None]:
    """拆成（LRC 正文，尾部结构）；没有标记就是纯 LRC。"""
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(NHLRC_MARK):
            body = "\n".join(lines[:i]).rstrip() + "\n"
            try:
                tail = json.loads("\n".join(lines[i + 1:]) or "{}")
            except Exception:
                return body, None
            return body, tail if isinstance(tail, dict) else None
    return text, None


def _seg_list(raw) -> list[list]:
    """容忍两种写法：["君","きみ","A"] 或 {"b":"君","r":"きみ","lv":"A"}"""
    out = []
    for item in raw or ():
        if isinstance(item, dict):
            out.append([item.get("b", ""), item.get("r"), item.get("lv")])
        elif isinstance(item, (list, tuple)) and item:
            out.append([item[0], (item[1] if len(item) > 1 else None),
                        (item[2] if len(item) > 2 else None)])
    return out


def annotations_for(lines: list[dict], tail: dict | None) -> dict[int, list]:
    """校验尾部标注：行号存在、哈希一致、拼起来等于正文 → 才认。"""
    if not tail or not tail.get("lines"):
        return {}
    ok: dict[int, list] = {}
    for ent in tail["lines"]:
        try:
            i = int(ent.get("i"))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(lines)):
            continue
        text = lines[i].get("text") or ""
        if ent.get("h") and ent["h"] != _hash8(text):
            continue
        seg = _seg_list(ent.get("seg"))
        if not seg or "".join(x[0] for x in seg) != text:
            continue
        ok[i] = seg
    return ok


def render_body(lines: list[dict], metadata: list[dict] | None = None) -> str:
    return render(lines, metadata)


def render_nhlrc(lines: list[dict], metadata: list[dict] | None = None,
                 annotations: dict[int, list] | None = None) -> str:
    body = render(lines, metadata)
    entries = []
    for i, seg in sorted((annotations or {}).items()):
        if 0 <= i < len(lines) and seg:
            entries.append({"i": i, "h": _hash8(lines[i].get("text") or ""),
                            "seg": seg})
    if not entries:
        return body
    tail = {"v": NHLRC_VERSION, "gen": GEN, "body": _hash8(body), "lines": entries}
    return body + "\n" + NHLRC_MARK + f" {NHLRC_VERSION}\n" + \
        json.dumps(tail, ensure_ascii=False, indent=1) + "\n"


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


def parse(text: str) -> list[dict]:
    """按文件顺序读取编辑行，保留还未打时间戳的非空文本。

    标准： [mm:ss.xx]文本
    JSON： {"t":毫秒,"c":[{"tx":"作词: "},{"tx":"Ayase"}]}
    """
    return _parse_document(text)[0]


def _parse_document(text: str) -> tuple[list[dict], list[dict]]:
    out, metadata = [], []
    for i, raw in enumerate((text or "").splitlines()):
        line = (raw.lstrip("\ufeff") if i == 0 else raw).strip()
        if not line:
            continue
        if METADATA.fullmatch(line):
            metadata.append({"before": len(out), "text": raw})
            continue
        m = LINE.match(line)
        if m:
            t = int(m.group(1)) * 60 + float(m.group(2))
            out.append({"t": round(t, 2), "text": m.group(3).strip()})
            continue
        if line.startswith("{") and '"t"' in line:      # 网易云 JSON 行
            try:
                obj = json.loads(line)
                t = float(obj.get("t", 0)) / 1000.0     # 毫秒 → 秒
                body = "".join((c or {}).get("tx", "") for c in (obj.get("c") or []))
                out.append({"t": round(t, 2), "text": body.strip()})
                continue
            except (AttributeError, TypeError, ValueError):
                pass
        out.append({"t": None, "text": raw})
    return out, metadata


def fmt(t: float | None) -> str:
    if t is None:
        return ""
    m = int(t // 60)
    s = t - m * 60
    return f"[{m:02d}:{s:05.2f}]"


def render(lines: list[dict], metadata: list[dict] | None = None) -> str:
    rows = [f"{fmt(ln.get('t'))}{ln.get('text') or ''}" for ln in lines]
    for tag in reversed(metadata or ()):
        rows.insert(min(tag["before"], len(lines)), tag["text"])
    return "\n".join(rows) + "\n"


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
