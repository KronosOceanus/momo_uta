#!/usr/bin/env python3
"""段 → HTML 的唯一实现（播放器共用）。

不依赖数据源，只吃 Annotator 的 segments 列表。
"""
from __future__ import annotations

import html
import json

CLASS = {"A": "ra", "AB": "rab", "B": "rb"}


def segments_html(segments: list[dict], *, candidates: bool = False,
                  editable_ab: bool = False, occ: int | None = None) -> str:
    """把片段列表渲染成 HTML。

    candidates   B 档有候选时包成可点的 .bc（带 data-cands / data-parts）
    editable_ab  A/AB 包成 .ew（编辑模式可点，带 data-start）
    occ          传入行号时，.bc 额外带 data-occ（"{行}-{词序}"），供按"位置"改读音
    """
    parts = []
    for seg in segments:
        base = html.escape(seg["base"])
        lvl = seg.get("level", "K")
        if not seg.get("ruby"):
            parts.append(base if lvl != "C" else f'<span class="cc">{base}</span>')
            continue
        ruby = f'<ruby class="{CLASS.get(lvl, "")}">{base}<rt>{html.escape(seg["ruby"])}</rt></ruby>'
        cands = seg.get("cands") or []
        if lvl == "B" and candidates and len(cands) >= 2:
            parts_attr = ""
            if seg.get("cand_parts"):
                parts_attr = f' data-parts="{html.escape(json.dumps(seg["cand_parts"], ensure_ascii=False))}"'
            occ_attr = f' data-occ="{occ}-{seg.get("word")}"' if occ is not None else ""
            ruby = (f'<span class="bc" data-start="{seg["start"]}"'
                    f' data-cands="{"|".join(cands)}"'
                    f' data-base="{html.escape(seg.get("wordbase") or seg["base"])}"'
                    f'{parts_attr}{occ_attr}>{ruby}</span>')
        elif editable_ab and (lvl in ("A", "AB") or lvl == "B"):
            # A/AB 恒可编辑；B 走到这里说明没有候选，编辑模式下也能手输
            ruby = (f'<span class="ew" data-start="{seg["start"]}"'
                    f' data-base="{html.escape(seg["base"])}">{ruby}</span>')
        parts.append(ruby)
    return "".join(parts)


def words_html(segments: list[dict], key: str = "romaji") -> str:
    """按 word 分组把罗马音包成 <span data-base>，供按词高亮。"""
    groups: dict = {}
    order = []
    for seg in segments:
        w = seg.get("word")
        if w not in groups:
            groups[w] = []
            order.append(w)
        groups[w].append(seg)
    parts = []
    for w in order:
        txt = "".join((s.get(key) or "") for s in groups[w])
        if not txt:
            continue
        base = "".join(s["base"] for s in groups[w])
        parts.append(f'<span class="w" data-base="{html.escape(base)}">{txt}</span>')
    return " ".join(parts)
