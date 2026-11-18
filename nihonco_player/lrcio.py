#!/usr/bin/env python3
"""读写 .lrc：解析、生成、备份、与歌词缓存同步。

只处理「时间戳 + 文本」这一层，BGM/元数据标签按普通行保留。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import lyrics as LY

LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")


def lrc_path(audio: str | Path) -> Path:
    return Path(audio).with_suffix(".lrc")


def exists(audio: str | Path) -> bool:
    return lrc_path(audio).is_file()


def load(audio: str | Path) -> dict:
    """优先读 .lrc 文件；没有就退回歌词缓存（网易云那套），方便首次导出成文件。"""
    audio = Path(audio)
    p = lrc_path(audio)
    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="ignore")
        return {"ok": True, "exists": True, "path": str(p), "text": text,
                "lines": parse(text)}
    artist, title = LY.split_name(audio.stem)
    hit = LY.get_lrc(title, artist) or {}
    text = hit.get("lrc") or ""
    return {"ok": True, "exists": False, "from_cache": bool(text), "path": str(p),
            "text": text, "lines": parse(text)}


def parse(text: str) -> list[dict]:
    out = []
    for raw in (text or "").splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        out.append({"t": round(t, 2), "text": m.group(3).strip()})
    return out


def fmt(t: float | None) -> str:
    if t is None:
        return ""
    m = int(t // 60)
    s = t - m * 60
    return f"[{m:02d}:{s:05.2f}]"


def render(lines: list[dict]) -> str:
    return "\n".join(f"{fmt(ln.get('t'))}{ln.get('text') or ''}" for ln in lines) + "\n"


def save(audio: str | Path, lines: list[dict]) -> dict:
    """写回 .lrc（首次备份成 .lrc.bak），并同步歌词缓存。"""
    audio = Path(audio)
    p = lrc_path(audio)
    p.parent.mkdir(parents=True, exist_ok=True)

    backed = False
    if p.is_file():
        bak = p.with_suffix(".lrc.bak")
        if not bak.exists():
            shutil.copy2(p, bak)
            backed = True

    text = render(lines)
    p.write_text(text, encoding="utf-8")

    artist, title = LY.split_name(audio.stem)
    LY.write_local_lrc(title, artist, text,
                       duration=LY.audio_duration(audio), name=title, by=artist)
    return {"ok": True, "path": str(p), "lines": len(lines), "backed_up": backed}
