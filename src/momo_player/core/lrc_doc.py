#!/usr/bin/env python3
"""LRC / nhlrc 文档格式：纯文本 ↔ 结构，无文件 IO。"""
from __future__ import annotations

import json
import re
import secrets

NHLRC_MARK = "#NHLRC"
GEN = "momo 0.1"

LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)(?:-\d+)?\](.*)$")
METADATA = re.compile(
    r"(?:\[(?:ar|al|ti|au|by|offset|length|re|ve|la|id|tool):[^\]\r\n]*\][ \t]*)+",
    re.IGNORECASE,
)
META_CREDIT = re.compile(
    r"^(?:作詞|作词|作曲|編曲|编曲|訳詞|訳词|制作|製作|演唱|歌"
    r"|Lyrics|Composer|Arranger|Producer|Composed|Produced)"
    r"\s*(?:by\s*)?[:：]",
    re.IGNORECASE,
)


def is_metadata_text(text: str) -> bool:
    """一行（已去掉时间戳）是不是 meta：标签行或制作信息行。"""
    s = (text or "").strip()
    if not s:
        return False
    if METADATA.fullmatch(s):
        return True
    # 行首有 metadata 标签时整行都算 metadata，和前端 rowKind 保持一致；
    # 不再根据标签后的正文二次判断。
    if METADATA.match(s):
        return True
    return bool(META_CREDIT.match(s))


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


def _new_lid() -> str:
    return "l_" + secrets.token_hex(4)


def _new_tid() -> str:
    return "t_" + secrets.token_hex(4)


def new_line_id() -> str:
    return _new_lid()


def new_token_ids(count: int) -> list[str]:
    return [_new_tid() for _ in range(max(0, int(count)))]


def align_translations(lines: list[dict], old_lines: list[dict],
                       translations: dict[int, str] | None) -> dict[int, str]:
    """插入/删除/移动行后，按位置 + 原文内容对齐翻译。"""
    entries = [(int(i), str(t)) for i, t in (translations or {}).items()
               if str(t or "").strip()]
    if not entries:
        return {}
    old = {i: (ln.get("text") or "") for i, ln in enumerate(old_lines or [])}
    new = {i: (ln.get("text") or "") for i, ln in enumerate(lines or [])}
    out: dict[int, str] = {}
    used: set[int] = set()
    for i, text in entries:
        if i < len(lines) and old.get(i) == new.get(i):
            out[i] = text
            used.add(i)
    rest = [(i, text) for i, text in entries if i not in used]
    for i, ln in enumerate(lines or []):
        if i in out:
            continue
        want = ln.get("text") or ""
        for k, (j, text) in enumerate(rest):
            if old.get(j, None) == want:
                out[i] = text
                rest.pop(k)
                break
    return out


def translations_from_lrc(trans_text: str, lines: list[dict],
                          tol: float = 0.05, loose: float = 0.2) -> dict[int, str]:
    """把 tlyric 一类独立 LRC 翻译配到原文行。

    1. 精确/±tol 时间戳
    2. ±loose 时间戳
    3. 两边行数相同才按行序一对一补齐
    """
    timed = parse_timed(trans_text)
    candidates = [(i, ln) for i, ln in enumerate(lines or []) if ln.get("t") is not None]
    if not timed or not candidates:
        return {}
    used: set[int] = set()
    assigned: dict[int, int] = {}
    out: dict[int, str] = {}

    def by_time(limit: float) -> None:
        for ti, tr in enumerate(timed):
            if ti in assigned:
                continue
            best = None
            for li, ln in candidates:
                if li in used:
                    continue
                d = abs(float(ln["t"]) - tr["t"])
                if d <= limit and (best is None or d < best[0]):
                    best = (d, li)
            if best:
                li = best[1]
                used.add(li)
                assigned[ti] = li
                out[li] = tr["text"]

    by_time(tol)
    by_time(loose)
    if len(timed) == len(candidates):
        for ti, (li, _) in enumerate(candidates):
            if ti in assigned or li in used:
                continue
            used.add(li)
            assigned[ti] = li
            out[li] = timed[ti]["text"]
    return out


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def utf16_to_cp(s: str, pos: int) -> int:
    """UTF-16 code unit offset → Python code point index。"""
    pos = max(0, min(int(pos), utf16_len(s)))
    n = 0
    for i, ch in enumerate(s):
        if n >= pos:
            return i
        n += 2 if ord(ch) > 0xFFFF else 1
    return len(s)


def tokens_with_spans(seg, tids, text: str) -> list[dict]:
    """把 seg + tid 转成编辑器 token；span/base 不匹配则返回空。"""
    if not seg or not isinstance(tids, list) or len(tids) != len(seg):
        return []
    cp = u16 = 0
    out = []
    for i, part in enumerate(seg):
        base = str(part[0] or "") if part else ""
        if not base:
            return []
        end_cp = cp + len(base)
        if text[cp:end_cp] != base:
            return []
        end_u16 = u16 + utf16_len(base)
        out.append({"tid": tids[i], "start": u16, "end": end_u16, "base": base,
                    "ruby": part[1] if len(part) > 1 else None,
                    "level": part[2] if len(part) > 2 else None})
        cp, u16 = end_cp, end_u16
    return out if not text[cp:].strip() else []


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


def _parse_rows(text: str) -> tuple[list[dict], list[dict], list[dict]]:
    """一次扫描产出 compact lines / metadata / 编辑器 body_rows。

    - compact lines：只保留非空歌词行，供播放和 annotation 使用
    - metadata：保留原始 metadata 行和 before 位置
    - body_rows：编辑器行，保留空行，不包含 metadata
    """
    lines: list[dict] = []
    metadata: list[dict] = []
    body_rows: list[dict] = []

    for i, raw in enumerate((text or "").splitlines()):
        line = (raw.lstrip("\ufeff") if i == 0 else raw).strip()
        if not line:
            body_rows.append({"t": None, "text": ""})
            continue
        if METADATA.fullmatch(line):
            metadata.append({"before": len(lines), "text": raw})
            continue

        parsed = None
        m = LINE.match(line)
        if m:
            parsed = {"t": round(int(m.group(1)) * 60 + float(m.group(2)), 2),
                      "text": m.group(3).strip()}
        elif line.startswith("{") and '"t"' in line:
            try:
                obj = json.loads(line)
                t = float(obj.get("t", 0)) / 1000.0
                body = "".join((c or {}).get("tx", "") for c in (obj.get("c") or []))
                parsed = {"t": round(t, 2), "text": body.strip()}
            except (AttributeError, TypeError, ValueError):
                parsed = None

        if parsed is None:
            parsed = {"t": None, "text": raw}
        # 编辑器保留这一行；空正文（即使带时间戳）不进入 compact lines。
        body_rows.append(dict(parsed))
        text = str(parsed.get("text") or "")
        if text.strip() and not is_metadata_text(text):
            lines.append(parsed)

    return lines, metadata, body_rows


def _parse_document(text: str) -> tuple[list[dict], list[dict]]:
    lines, metadata, _body_rows = _parse_rows(text)
    return lines, metadata


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


