#!/usr/bin/env python3
"""LRC / nhlrc 文档格式：纯文本 ↔ 结构，无文件 IO。"""
from __future__ import annotations

import hashlib
import json
import re

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


def parse(text: str) -> list[dict]:
    """按文件顺序读取编辑行，保留还未打时间戳的非空文本。

    标准： [mm:ss.xx]文本
    JSON： {"t":毫秒,"c":[{"tx":"作词: "},{"tx":"Ayase"}]}
    """
    return _parse_document(text)[0]


def parse_timed(text: str) -> list[dict]:
    """只要"打了时间戳且有文本"的行，按时间排序（缓存/匹配用）。"""
    out = []
    for raw in (text or "").splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        body = m.group(3).strip()
        if body:
            out.append({"t": round(t, 2), "text": body})
    out.sort(key=lambda x: x["t"])
    return out


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


