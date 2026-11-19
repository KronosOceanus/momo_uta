#!/usr/bin/env python3
"""读写 .lrc：解析、生成、备份、与歌词缓存同步。

编辑行保留无时间戳的文本。文件元数据独立保留。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import lyrics as LY

LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)(?:-\d+)?\](.*)$")
METADATA = re.compile(
    r"(?:\[(?:ar|al|ti|au|by|offset|length|re|ve|la|id|tool):[^\]\r\n]*\][ \t]*)+",
    re.IGNORECASE,
)


def lrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".lrc")


def exists(audio: str | Path) -> bool:
    return lrc_path(audio).is_file()


def load(audio: str | Path) -> dict:
    """优先读 .lrc 文件；没有就退回歌词缓存（网易云那套），方便首次导出成文件。"""
    audio = Path(audio)
    p = lrc_path(audio)
    exists = p.is_file()
    if exists:
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        artist, title = LY.split_name(audio.stem)
        text = (LY.get_lrc(title, artist) or {}).get("lrc") or ""
    lines, metadata = _parse_document(text)
    return {"ok": True, "exists": exists, "from_cache": not exists and bool(text),
            "path": str(p), "text": text, "lines": lines, "metadata": metadata}


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
    return Path(audio).with_suffix(".lrc.bak")


def backup_status(audio: str | Path) -> dict:
    b = backup_path(audio)
    if not b.is_file():
        return {"exists": False}
    text = b.read_text(encoding="utf-8", errors="ignore")
    return {"exists": True, "path": str(b), "lines": len(parse(text)),
            "mtime": b.stat().st_mtime, "size": b.stat().st_size}


def restore_backup(audio: str | Path) -> dict:
    """把 .lrc.bak 覆盖回 .lrc（恢复最初版本），并同步歌词缓存。"""
    audio = Path(audio)
    b = backup_path(audio)
    if not b.is_file():
        return {"ok": False, "error": "没有备份文件"}
    p = lrc_path(audio)
    shutil.copy2(b, p)
    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, p.read_text(encoding="utf-8"),
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(parse(p.read_text(encoding="utf-8")))}


def import_text(audio: str | Path, text: str) -> dict:
    """用外部 .lrc 文本直接覆盖当前歌词（首次覆盖前备份）。"""
    audio = Path(audio)
    p = lrc_path(audio)
    p.parent.mkdir(parents=True, exist_ok=True)
    backed = False
    if p.is_file():
        bak = p.with_suffix(".lrc.bak")
        if not bak.exists():
            shutil.copy2(p, bak)
            backed = True
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text, encoding="utf-8")
    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, text,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(parse(text)), "backed_up": backed}


def save(audio: str | Path, lines: list[dict]) -> dict:
    """写回 .lrc（首次备份成 .lrc.bak），并同步歌词缓存。"""
    audio = Path(audio)
    p = lrc_path(audio)
    p.parent.mkdir(parents=True, exist_ok=True)

    artist, title = LY.split_name(audio.stem)
    original = ""
    backed = False
    if p.is_file():
        original = p.read_text(encoding="utf-8", errors="ignore")
        bak = backup_path(audio)
        if not bak.exists():
            shutil.copy2(p, bak)
            backed = True
    elif LY._cached(title, artist):
        original = (LY.get_lrc(title, artist) or {}).get("lrc") or ""

    _, metadata = _parse_document(original)
    text = render(lines, metadata)
    p.write_text(text, encoding="utf-8")
    LY.write_local_lrc(title, artist, text,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(lines), "backed_up": backed}
