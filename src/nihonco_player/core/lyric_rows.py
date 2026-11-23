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
from pathlib import Path

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


def _row_from_line(raw: str, first: bool = False) -> dict:
    line = raw.lstrip("\ufeff") if first else raw
    stripped = line.strip()
    if not stripped:
        return {"kind": "blank", "text": "", "t": None}
    if DOC.METADATA.fullmatch(stripped):
        return {"kind": "metadata", "text": raw, "t": None}
    m = DOC.LINE.match(stripped)
    if m:
        t = round(int(m.group(1)) * 60 + float(m.group(2)), 2)
        text = m.group(3).strip()
        return ({"kind": "lyric", "text": text, "t": t} if text
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
    pos = 0
    out = []
    for i, part in enumerate(seg):
        base = str(part[0] or "") if part else ""
        if not base:
            return []
        end = pos + len(base)
        if text[pos:end] != base:
            return []
        out.append({"tid": tids[i], "start": pos, "end": end, "base": base,
                    "ruby": part[1] if len(part) > 1 else None,
                    "level": part[2] if len(part) > 2 else None})
        pos = end
    return out if pos == len(text) else []


def parse_rows(text: str) -> list[dict]:
    """解析 v2 文档为 rows；尾部的 i 是 body 行号。"""
    body, tail = _split_document(text)
    if tail is not None and tail.get("v") != VERSION:
        raise ValueError("unsupported nhlrc version")
    raw_lines = body.splitlines()
    rows = []
    lyric_by_i = {}
    for i, raw in enumerate(raw_lines):
        row = _row_from_line(raw, first=(i == 0))
        row = {"id": _new_row_id(), **row, "lid": None, "tokens": [], "trans": ""}
        rows.append(row)
        if row["kind"] == "lyric":
            lyric_by_i[i] = row

    entries = {}
    for ent in (tail or {}).get("lines") or []:
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
        seg = [list(x) if isinstance(x, (list, tuple)) else x
               for x in (ent.get("seg") or [])]
        seg = [[x.get("b", ""), x.get("r"), x.get("lv")] if isinstance(x, dict) else x
               for x in seg]
        if seg and "".join(str(x[0] or "") for x in seg) != row["text"]:
            continue
        row["lid"] = ent.get("lid") or _new_lid()
        tids = ent.get("tid") or []
        row["tokens"] = _tokens(seg, tids, row["text"])
        entries[i] = row

    for ent in (tail or {}).get("trans") or []:
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


def render_rows(rows: list[dict], trans_lang: str = "zh") -> str:
    body = body_text(rows)
    lines = []
    trans = []
    for i, row in enumerate(rows):
        if row.get("kind") != "lyric":
            continue
        lid = row.get("lid") or _new_lid()
        row["lid"] = lid
        tokens = row.get("tokens") or []
        seg = [[tok["base"], tok.get("ruby"), tok.get("level")] for tok in tokens]
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
    return body + "\n" + DOC.NHLRC_MARK + f" {VERSION}\n" + json.dumps(
        tail, ensure_ascii=False, indent=1) + "\n"


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
    pos = max(0, min(len(text), int(pos)))
    left_text, right_text = text[:pos], text[pos:]
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
        offset = len(left_text)
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
