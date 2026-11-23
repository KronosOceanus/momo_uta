#!/usr/bin/env python3
"""歌词单一行模型（v2）。

- rows 是唯一权威行列表，包含 lyric / blank / metadata
- 播放视图从 rows 派生
- 不读取、不迁移 v1
"""
from __future__ import annotations

import hashlib
import json
import secrets

from . import lrc_doc as DOC

VERSION = 2
ROW_KINDS = {"lyric", "blank", "metadata"}


def _hash8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _new_row_id() -> str:
    return "r_" + secrets.token_hex(4)


def _new_lid() -> str:
    return "l_" + secrets.token_hex(4)


def _new_tid() -> str:
    return "t_" + secrets.token_hex(4)


def _split_document(text: str) -> tuple[str, dict | None]:
    """保留正文尾部空行；只接受 v2 尾部。"""
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(DOC.NHLRC_MARK):
            body = "\n".join(lines[:i])
            try:
                tail = json.loads("\n".join(lines[i + 1:]) or "{}")
            except Exception:
                tail = None
            return body, tail if isinstance(tail, dict) else None
    return text, None


def _tail_list(tail: dict | None, key: str) -> list:
    value = (tail or {}).get(key)
    return value if isinstance(value, list) else []


def _row_from_line(raw: str, first: bool = False) -> dict:
    line = raw.lstrip("\ufeff") if first else raw
    stripped = line.strip()
    if not stripped:
        return {"kind": "blank", "text": "", "t": None}
    if DOC.METADATA.fullmatch(stripped):
        return {"kind": "metadata", "text": raw, "t": None}
    m = DOC.LINE.match(line)
    if m:
        t = round(int(m.group(1)) * 60 + float(m.group(2)), 2)
        text = m.group(3)
        return ({"kind": "lyric", "text": text, "t": t} if text.strip()
                else {"kind": "blank", "text": "", "t": t})
    if stripped.startswith("{") and '"t"' in stripped:
        try:
            obj = json.loads(stripped)
            t = float(obj.get("t", 0)) / 1000.0
            text = "".join((c or {}).get("tx", "") for c in (obj.get("c") or [])).strip()
            return ({"kind": "lyric", "text": text, "t": round(t, 2)} if text
                    else {"kind": "blank", "text": "", "t": round(t, 2)})
        except (AttributeError, TypeError, ValueError):
            pass
    return {"kind": "lyric", "text": raw, "t": None}


def _tokens(seg, tids, text: str) -> list[dict]:
    if not seg or not isinstance(tids, list) or len(tids) != len(seg):
        return []
    pos = u16 = 0
    out = []
    for i, part in enumerate(seg):
        if not isinstance(part, (list, tuple)) or not part:
            return []
        base = str(part[0] or "")
        if not base:
            return []
        end_cp = pos + len(base)
        if text[pos:end_cp] != base:
            return []
        end = u16 + DOC.utf16_len(base)
        out.append({"tid": tids[i], "start": u16, "end": end, "base": base,
                    "ruby": part[1] if len(part) > 1 else None,
                    "level": part[2] if len(part) > 2 else None})
        pos, u16 = end_cp, end
    return out if not text[pos:].strip() else []


def parse_rows(text: str) -> list[dict]:
    """解析 v2 文档为 rows；尾部的 i 是 body 行号。"""
    body, tail = _split_document(text)
    if tail is not None and tail.get("v") != VERSION:
        raise ValueError("unsupported nhlrc version")
    raw_lines = body.splitlines()
    rows = []
    for i, raw in enumerate(raw_lines):
        row = _row_from_line(raw, first=(i == 0))
        row = {"id": _new_row_id(), **row, "lid": None, "tokens": [], "trans": ""}
        rows.append(row)


    for ent in _tail_list(tail, "lines"):
        if not isinstance(ent, dict):
            continue
        try:
            i = int(ent.get("i"))
        except (TypeError, ValueError):
            continue
        row = rows[i] if 0 <= i < len(rows) else None
        if not row or row["kind"] != "lyric":
            continue
        h = ent.get("h")
        if h and h != _hash8(row["text"]):
            continue
        raw_seg = ent.get("seg")
        if raw_seg is None:
            raw_seg = []
        if not isinstance(raw_seg, list):
            continue
        seg = []
        bad = False
        for x in raw_seg:
            if isinstance(x, (list, tuple)):
                seg.append(list(x))
            elif isinstance(x, dict):
                seg.append([x.get("b", ""), x.get("r"), x.get("lv")])
            else:
                bad = True
                break
        if bad:
            continue
        if seg and "".join(str(x[0] or "") for x in seg) != row["text"].rstrip():
            continue
        row["lid"] = ent.get("lid") or _new_lid()
        tids = ent.get("tid") or []
        row["tokens"] = _tokens(seg, tids, row["text"])

    for ent in _tail_list(tail, "trans"):
        if not isinstance(ent, dict):
            continue
        try:
            i = int(ent.get("i"))
        except (TypeError, ValueError):
            continue
        row = rows[i] if 0 <= i < len(rows) else None
        if not row or row["kind"] != "lyric":
            continue
        if ent.get("lid") and row.get("lid") and ent["lid"] != row["lid"]:
            continue
        if ent.get("h") and ent["h"] != _hash8(row["text"]):
            continue
        row["trans"] = str(ent.get("text") or "")

    # 没有尾部的纯正文，也给 lyric 行补一个临时身份。
    for row in rows:
        if row["kind"] == "lyric" and not row.get("lid"):
            row["lid"] = _new_lid()
    return rows


def body_text(rows: list[dict]) -> str:
    out = []
    for row in rows:
        kind = row.get("kind")
        if kind == "metadata":
            out.append(row.get("text") or "")
        elif kind == "blank":
            out.append(DOC.fmt(row.get("t")) if row.get("t") is not None else "")
        else:
            out.append(DOC.fmt(row.get("t")) + (row.get("text") or ""))
    return "\n".join(out) + "\n"


def _tokens_valid(row: dict) -> bool:
    text = row.get("text") or ""
    cp = u16 = 0
    for tok in row.get("tokens") or []:
        base = tok.get("base") or ""
        if not base or tok.get("start") != u16:
            return False
        if text[cp:cp + len(base)] != base:
            return False
        cp += len(base)
        u16 += DOC.utf16_len(base)
        if tok.get("end") != u16:
            return False
    return bool(row.get("tokens")) and not text[cp:].strip()


def repair_tokens(row: dict) -> None:
    """正文改了但 token 只覆盖一部分时，补齐分段并保留未改部分的手工读音。"""
    if row.get("kind") != "lyric" or _tokens_valid(row):
        return
    old = [dict(t) for t in (row.get("tokens") or [])]
    text = row.get("text") or ""
    if not old:
        return
    try:
        from .annotation import annotate_line_with_notes, segs_of
        result = annotate_line_with_notes(text)
        segs = segs_of(result)
    except Exception:
        return
    by_span = {(t.get("start"), t.get("end"), t.get("base")): t for t in old}
    out = []
    cp = u16 = 0
    for part in segs:
        base = part[0] or ""
        end_cp = cp + len(base)
        end_u16 = u16 + DOC.utf16_len(base)
        found = by_span.get((u16, end_u16, base))
        if found:
            ruby, level, tid = found.get("ruby"), found.get("level"), found.get("tid")
        else:
            ruby, level = part[1], part[2]
            tid = None
        if not tid:
            tid = _new_tid()
        out.append({"tid": tid, "start": u16, "end": end_u16, "base": base,
                    "ruby": ruby, "level": level})
        cp, u16 = end_cp, end_u16
    if not text[cp:].strip():
        row["tokens"] = out


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _dump_tail(tail: dict) -> str:
    """外层字段换行；每条标注/翻译压成一行，便于 diff。"""
    parts = [f' "v": {json.dumps(tail["v"])}',
             f' "gen": {json.dumps(tail["gen"], ensure_ascii=False)}',
             f' "body": {json.dumps(tail["body"])}']
    lines = tail.get("lines") or []
    parts.append(' "lines": [\n' + ",\n".join("  " + _compact(x) for x in lines)
                 + "\n ]" if lines else ' "lines": []')
    if "trans_lang" in tail:
        parts.append(f' "trans_lang": {json.dumps(tail["trans_lang"], ensure_ascii=False)}')
    trans = tail.get("trans") or []
    if trans:
        parts.append(' "trans": [\n' + ",\n".join("  " + _compact(x) for x in trans)
                     + "\n ]")
    return "{\n" + ",\n".join(parts) + "\n}"


def render_rows(rows: list[dict], trans_lang: str = "zh") -> str:
    for row in rows:
        repair_tokens(row)
    body = body_text(rows)
    lines = []
    trans = []
    for i, row in enumerate(rows):
        if row.get("kind") != "lyric":
            continue
        lid = row.get("lid") or _new_lid()
        row["lid"] = lid
        tokens = row.get("tokens") or []
        seg = []
        for tok in tokens:
            part = [tok["base"], tok.get("ruby")]
            if tok.get("level") != "K":      # K 是纯假名默认档，省略即可
                part.append(tok.get("level"))
            seg.append(part)
        tids = [tok["tid"] for tok in tokens]
        lines.append({"i": i, "lid": lid, "h": _hash8(row.get("text") or ""),
                      "seg": seg, "tid": tids})
        text = str(row.get("trans") or "").strip()
        if text:
            trans.append({"i": i, "lid": lid, "h": _hash8(row.get("text") or ""),
                          "text": text})
    tail = {"v": VERSION, "gen": DOC.GEN, "body": _hash8(body), "lines": lines}
    if trans:
        tail["trans_lang"] = str(trans_lang or "zh")
        tail["trans"] = trans
    return body + "\n" + DOC.NHLRC_MARK + f" {VERSION}\n" + _dump_tail(tail) + "\n"


def playable(rows: list[dict]) -> list[dict]:
    items = [(i, r) for i, r in enumerate(rows)
             if r.get("kind") == "lyric" and r.get("t") is not None]
    items.sort(key=lambda item: (item[1]["t"], item[0]))
    return [r for _, r in items]


def split_row(row: dict, pos: int) -> tuple[dict, dict]:
    """按正文位置拆 lyric row；原内容和 lid 留在非空侧。"""
    if row.get("kind") != "lyric":
        raise ValueError("只能拆 lyric 行")
    text = row.get("text") or ""
    pos = max(0, min(DOC.utf16_len(text), int(pos)))
    cp = DOC.utf16_to_cp(text, pos)
    left_text, right_text = text[:cp], text[cp:]
    tokens = row.get("tokens") or []
    left_tokens = [dict(t) for t in tokens if t["end"] <= pos]
    right_tokens = [{**t, "start": t["start"] - pos, "end": t["end"] - pos}
                    for t in tokens if t["start"] >= pos]
    left_empty, right_empty = not left_text.strip(), not right_text.strip()
    origin_lid = row.get("lid") or _new_lid()
    origin_id = row.get("id") or _new_row_id()
    trans = row.get("trans") or ""
    if left_empty and not right_empty:
        left = {"id": _new_row_id(), "kind": "blank", "text": "", "t": row.get("t"),
                "lid": _new_lid(), "tokens": [], "trans": ""}
        right = {"id": origin_id, "kind": "lyric", "text": right_text,
                 "t": row.get("t") if row.get("t") is not None else None,
                 "lid": origin_lid, "tokens": right_tokens, "trans": trans}
        return left, right
    left = {"id": origin_id, "kind": "lyric" if left_text else "blank",
            "text": left_text, "t": row.get("t") if left_text else None,
            "lid": origin_lid if left_text else _new_lid(),
            "tokens": left_tokens, "trans": trans if left_text else ""}
    right = {"id": _new_row_id(), "kind": "blank" if not right_text else "lyric",
             "text": right_text, "t": None,
             "lid": _new_lid(), "tokens": right_tokens,
             "trans": ""}
    return left, right


def merge_rows(left: dict, right: dict) -> dict:
    """合并两行；非空内容侧的 row.id/lid 优先，tokens 平移。"""
    left_text = left.get("text") or ""
    right_text = right.get("text") or ""
    left_content = bool(left_text.strip())
    right_content = bool(right_text.strip())
    if left_content or not right_content:
        target = left
        tokens = [dict(t) for t in (left.get("tokens") or [])]
        offset = DOC.utf16_len(left_text)
        tokens += [{**t, "start": t["start"] + offset, "end": t["end"] + offset}
                   for t in (right.get("tokens") or [])]
    else:
        target = right
        tokens = [dict(t) for t in (right.get("tokens") or [])]
    parts = [str(x).strip() for x in (left.get("trans"), right.get("trans"))
             if x and str(x).strip()]
    target = dict(target)
    target["text"] = left_text + right_text
    target["t"] = left.get("t") if left.get("t") is not None else right.get("t")
    target["kind"] = "lyric" if (left_text + right_text).strip() else "blank"
    target["tokens"] = tokens
    target["trans"] = " ".join(parts)
    if not target.get("lid"):
        target["lid"] = _new_lid()
    return target
