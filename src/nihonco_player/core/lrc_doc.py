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


def annotations_for(lines: list[dict], tail: dict | None,
                    strict: bool = True) -> dict[int, list]:
    """校验尾部标注：行号存在、哈希一致、拼起来等于正文 → 才认。

    strict=False 时跳过逐行哈希比对（正文整体哈希已验证，见 lrc_files.load）。
    """
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
        if strict and ent.get("h") and ent["h"] != _hash8(text):
            continue
        seg = _seg_list(ent.get("seg"))
        if not seg or "".join(x[0] for x in seg) != text:
            continue
        ok[i] = seg
    return ok


def translations_for(lines: list[dict], tail: dict | None,
                      strict: bool = True) -> dict[int, str]:
    """校验尾部翻译：行号存在、hash 一致、文本非空才认。"""
    if not tail or not tail.get("trans"):
        return {}
    out: dict[int, str] = {}
    for ent in tail["trans"]:
        try:
            i = int(ent.get("i"))
            text = str(ent.get("text") or "").strip()
        except (AttributeError, TypeError, ValueError):
            continue
        if not text or not (0 <= i < len(lines)):
            continue
        if strict and ent.get("h") and ent["h"] != _hash8(lines[i].get("text") or ""):
            continue
        out[i] = text
    return out


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
    for i, text in entries:                       # 位置 + 内容都没变
        if i < len(lines) and old.get(i, None) == new.get(i) and new.get(i) == old.get(i):
            out[i] = text
            used.add(i)
    rest = [(i, text) for i, text in entries if i not in used]
    for i, ln in enumerate(lines or []):          # 按原文内容 FIFO 找
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
                          tol: float = 0.05) -> dict[int, str]:
    """把 tlyric 一类独立 LRC 翻译按时间戳配到原文行。"""
    timed = parse_timed(trans_text)
    if not timed:
        return {}
    used: set[int] = set()
    out: dict[int, str] = {}
    for tr in timed:
        best = None
        for i, ln in enumerate(lines or []):
            if i in used or ln.get("t") is None:
                continue
            d = abs(float(ln["t"]) - tr["t"])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        if best:
            used.add(best[1])
            out[best[1]] = tr["text"]
    return out


def render_body(lines: list[dict], metadata: list[dict] | None = None) -> str:
    return render(lines, metadata)


def render_nhlrc(lines: list[dict], metadata: list[dict] | None = None,
                 annotations: dict[int, list] | None = None,
                 translations: dict[int, str] | None = None) -> str:
    body = render(lines, metadata)
    entries = []
    for i, seg in sorted((annotations or {}).items()):
        if 0 <= i < len(lines) and seg:
            entries.append({"i": i, "h": _hash8(lines[i].get("text") or ""),
                            "seg": seg})
    trans = []
    for i, text in sorted((translations or {}).items()):
        text = str(text or "").strip()
        if text and 0 <= i < len(lines):
            trans.append({"i": i, "h": _hash8(lines[i].get("text") or ""),
                          "text": text})
    if not entries and not trans:
        return body
    # 尾部一行一条：体积小、diff 可读、每行都能单独定位
    rows = []
    for ent in entries:
        seg = json.dumps(ent["seg"], ensure_ascii=False, separators=(",", ":"))
        rows.append(f'  {{"i": {ent["i"]}, "h": "{ent["h"]}", "seg": {seg}}}')
    tail = ('{\n'
            f' "v": {NHLRC_VERSION},\n'
            f' "gen": "{GEN}",\n'
            f' "body": "{_hash8(body)}",\n'
            ' "lines": [\n' + ",\n".join(rows) + '\n ]')
    if trans:
        trows = []
        for ent in trans:
            t = json.dumps(ent["text"], ensure_ascii=False)
            trows.append(f'  {{"i": {ent["i"]}, "h": "{ent["h"]}", "text": {t}}}')
        tail += (',\n "trans_lang": "zh",\n'
                 ' "trans": [\n' + ",\n".join(trows) + '\n ]')
    tail += '\n}'
    return body + "\n" + NHLRC_MARK + f" {NHLRC_VERSION}\n" + tail + "\n"


def parse(text: str) -> list[dict]:
    """按文件顺序读取编辑行，保留还未打时间戳的非空文本。

    标准： [mm:ss.xx]文本
    JSON： {"t":毫秒,"c":[{"tx":"作词: "},{"tx":"Ayase"}]}
    """
    return _parse_document(text)[0]


def align_annotations(lines: list[dict],
                      annotations: dict[int, list]) -> dict[int, list]:
    """把已有标注按内容对齐到新行序（插入/删除/移动后仍然跟着行走）。

    位置优先（没动过的行最精确），再按文本先进先出；拼接不成立的一律不用。
    """
    entries = [(i, seg) for i, seg in sorted((annotations or {}).items()) if seg]
    texts = {i: "".join(x[0] for x in seg) for i, seg in entries}
    used: set[int] = set()
    out: dict[int, list] = {}

    for i, seg in entries:                       # 第一轮：位置 + 内容都一致
        if i < len(lines) and texts[i] == (lines[i].get("text") or ""):
            out[i] = seg
            used.add(i)

    remaining = [(i, seg) for i, seg in entries if i not in used]
    for i, ln in enumerate(lines):               # 第二轮：按内容找（FIFO）
        if i in out:
            continue
        want = ln.get("text") or ""
        for k, (j, seg) in enumerate(remaining):
            if texts[j] == want:
                out[i] = seg
                remaining.pop(k)
                break
    return out


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


