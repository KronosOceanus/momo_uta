#!/usr/bin/env python3
"""LRC / nhlrc 文档格式：纯文本 ↔ 结构，无文件 IO。"""
from __future__ import annotations

import hashlib
import json
import re
import secrets

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


ID_RE = re.compile(r"^[lt]_[0-9a-f]{8}$")


def _new_lid() -> str:
    return "l_" + secrets.token_hex(4)


def _new_tid() -> str:
    return "t_" + secrets.token_hex(4)


def new_line_id() -> str:
    return _new_lid()


def new_token_ids(count: int) -> list[str]:
    return [_new_tid() for _ in range(max(0, int(count)))]


def _unique_id(prefix: str, seen: set[str]) -> str:
    for _ in range(100):
        candidate = _new_lid() if prefix == "l" else _new_tid()
        if candidate not in seen:
            return candidate
    # 极端情况下退回确定性序号，仍满足格式
    for n in range(10000):
        candidate = f"{prefix}_{n:08x}"
        if candidate not in seen:
            return candidate
    raise RuntimeError("无法生成唯一歌词身份")


def _legacy_lid(i: int, text: str) -> str:
    raw = f"line\0{i}\0{text}".encode("utf-8")
    return "l_" + hashlib.sha1(raw).hexdigest()[:8]


def _legacy_tid(i: int, text: str, ti: int, base: str) -> str:
    raw = f"token\0{i}\0{ti}\0{base}\0{text}".encode("utf-8")
    return "t_" + hashlib.sha1(raw).hexdigest()[:8]


def _valid_id(value, prefix: str) -> bool:
    return isinstance(value, str) and value.startswith(prefix + "_") and bool(ID_RE.fullmatch(value))


def annotations_and_ids_for(lines: list[dict], tail: dict | None,
                            strict: bool = True) -> tuple[dict[int, list], dict[int, str], dict[int, list[str]]]:
    """按旧逻辑校验 seg，同时返回行/token 身份。

    旧文件没有 lid/tid 时生成确定性 legacy id；不写回。
    """
    if not tail or not tail.get("lines"):
        return {}, {}, {}
    ok: dict[int, list] = {}
    lids: dict[int, str] = {}
    tids: dict[int, list[str]] = {}
    seen_l: set[str] = set()
    seen_t: set[str] = set()
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
        lid = ent.get("lid")
        if not _valid_id(lid, "l") or lid in seen_l:
            lid = _legacy_lid(i, text)
        seen_l.add(lid)
        ids = ent.get("tid")
        if not isinstance(ids, list) or len(ids) != len(seg):
            ids = []
        out_ids = []
        for ti, part in enumerate(seg):
            tid = ids[ti] if ti < len(ids) else None
            if not _valid_id(tid, "t") or tid in seen_t:
                tid = _legacy_tid(i, text, ti, str(part[0] or ""))
            seen_t.add(tid)
            out_ids.append(tid)
        ok[i] = seg
        lids[i] = lid
        tids[i] = out_ids
    return ok, lids, tids


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
        if i < len(lines) and old.get(i) == new.get(i):
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


def render_body(lines: list[dict], metadata: list[dict] | None = None) -> str:
    return render(lines, metadata)


def render_nhlrc(lines: list[dict], metadata: list[dict] | None = None,
                 annotations: dict[int, list] | None = None,
                 translations: dict[int, str] | None = None,
                 trans_lang: str = "zh",
                 line_ids: dict[int, str] | None = None,
                 token_ids: dict[int, list[str]] | None = None,
                 annotation_index: dict[int, int] | None = None) -> str:
    body = render(lines, metadata)
    entries = []
    seen_l: set[str] = set()
    seen_t: set[str] = set()
    for i, seg in sorted((annotations or {}).items()):
        if 0 <= i < len(lines) and seg:
            tail_i = (annotation_index or {}).get(i, i)
            ent = {"i": tail_i, "h": _hash8(lines[i].get("text") or ""), "seg": seg}
            lid = (line_ids or {}).get(i)
            if lid is not None:
                if not _valid_id(lid, "l") or lid in seen_l:
                    lid = _unique_id("l", seen_l)
                ent["lid"] = lid
                seen_l.add(lid)
            tids = (token_ids or {}).get(i)
            if tids is not None:
                if not isinstance(tids, list) or len(tids) != len(seg):
                    tids = [None] * len(seg)
                final = []
                for tid in tids:
                    if not _valid_id(tid, "t") or tid in seen_t:
                        tid = _unique_id("t", seen_t)
                    final.append(tid)
                    seen_t.add(tid)
                ent["tid"] = final
            entries.append(ent)
    trans = []
    for i, text in sorted((translations or {}).items()):
        text = str(text or "").strip()
        if text and 0 <= i < len(lines):
            tail_i = (annotation_index or {}).get(i, i)
            trans.append({"i": tail_i, "h": _hash8(lines[i].get("text") or ""),
                          "text": text})
    if not entries and not trans:
        return body
    # 尾部一行一条：体积小、diff 可读、每行都能单独定位
    rows = []
    for ent in entries:
        parts = [f'"i": {ent["i"]}', f'"h": "{ent["h"]}"']
        if ent.get("lid"):
            parts.append(f'"lid": {json.dumps(ent["lid"], ensure_ascii=False)}')
        parts.append(f'"seg": {json.dumps(ent["seg"], ensure_ascii=False, separators=(",", ":"))}')
        if ent.get("tid"):
            parts.append(f'"tid": {json.dumps(ent["tid"], ensure_ascii=False, separators=(",", ":"))}')
        rows.append("  {" + ", ".join(parts) + "}")
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
        tail += (f',\n "trans_lang": {json.dumps(str(trans_lang or "zh"), ensure_ascii=False)},\n'
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


def _parse_body_rows(text: str) -> list[dict]:
    """编辑器行：保留空行，排除 metadata；与 compact lines 分开。"""
    out = []
    for i, raw in enumerate((text or "").splitlines()):
        line = (raw.lstrip("\ufeff") if i == 0 else raw).strip()
        if not line:
            out.append({"t": None, "text": ""})
            continue
        if METADATA.fullmatch(line):
            continue
        m = LINE.match(line)
        if m:
            out.append({"t": round(int(m.group(1)) * 60 + float(m.group(2)), 2),
                        "text": m.group(3).strip()})
            continue
        if line.startswith("{") and '"t"' in line:
            try:
                obj = json.loads(line)
                t = float(obj.get("t", 0)) / 1000.0
                body = "".join((c or {}).get("tx", "") for c in (obj.get("c") or []))
                out.append({"t": round(t, 2), "text": body.strip()})
                continue
            except (AttributeError, TypeError, ValueError):
                pass
        out.append({"t": None, "text": raw})
    return out


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


