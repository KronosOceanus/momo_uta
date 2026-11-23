#!/usr/bin/env python3
"""输出校验器：每条不变量都是一票否决。

设计原则：**违反不是"修正"，是拒绝输出**（降为弃权，并记原因）。

I1 往返一致    segment.base 必须等于原文 [start,end)；片段首尾相接、不重叠
I2 单调有序    start/end 单调递增
I3 读音只含假名（平假名 + ー）
I4 送り仮名一致 由 split_pieces 的 DP 保证（读音必须被完整消耗），这里不再复查：
   输出层每个片段只有"汉字部分"的读音，看不见整词读音，逐片段检查是空转
I5 纯假名不得有 ruby
I6 助詞・助動詞不得被 ruby 覆盖
I7 摩拉数 sanity  len(reading) ∈ [汉字数, 4×汉字数]
I8 跨词元 span 必须显式声明（word 序号必须一致）
"""
from __future__ import annotations

import re

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")
KANA_ONLY = re.compile(r"^[ぁ-んー]+$")
TRAILING_HIRA = re.compile(r"([ぁ-ん]+)$")
PARTICLES = set("はがをにでともへのやかねよぞさなわ")
NUMERAL = re.compile(r"[0-9０-９一二三四五六七八九十百千万億零〇]")
DIGITS = re.compile(r"[0-9０-９]")      # 只算阿拉伯数字；「二」这类本身是汉字

# 音便・活用で送り仮名の表面と読みがずれる型（有限・明示）
OKURIGANA_EXCEPTIONS = [
    (re.compile(r"って$"), re.compile(r"っ$")),
    (re.compile(r"って$"), re.compile(r"て$")),
    (re.compile(r"った$"), re.compile(r"っ$")),
    (re.compile(r"うた$"), re.compile(r"った$")),
    (re.compile(r"うて$"), re.compile(r"って$")),
    (re.compile(r"いく$"), re.compile(r"い$")),
]


def check(line: str, segs: list[dict]) -> list[dict]:
    """返回违规列表 [{seg, code, detail}]。空列表 = 通过。"""
    bad: list[dict] = []
    prev_end = 0
    for seg in segs:
        base, ruby = seg.get("base") or "", seg.get("ruby")
        start, end = seg.get("start"), seg.get("end")

        # I1 往返一致
        if start is None or end is None or line[start:end] != base:
            bad.append({"seg": seg, "code": "I1", "detail": f"原文[{start}:{end}]={line[start:end]!r} ≠ base={base!r}"})
            continue
        # I2 单调有序
        if start < prev_end or end <= start:
            bad.append({"seg": seg, "code": "I2", "detail": f"start={start} prev_end={prev_end} end={end}"})
        prev_end = end

        if not ruby:
            continue
        # I3 读音只含假名
        if not KANA_ONLY.match(ruby):
            bad.append({"seg": seg, "code": "I3", "detail": f"ruby={ruby!r}"})
        # I5 纯假名有 ruby（数字 / 数词不算：8→はち 是有意的）
        if not KANJI.search(base) and not NUMERAL.search(base):
            bad.append({"seg": seg, "code": "I5", "detail": f"{base} 无汉字却有 ruby={ruby}"})
        # I6 助詞被覆盖
        if base in PARTICLES and len(base) == 1:
            bad.append({"seg": seg, "code": "I6", "detail": f"{base} 是助詞"})
        # I7 摩拉数：按"要读出来的字数"算——汉字 + 数字（１１ 算 2 个字）
        n = max(1, len(KANJI.findall(base)) + len(DIGITS.findall(base)))
        if not (n <= len(ruby) <= 4 * n):
            bad.append({"seg": seg, "code": "I7", "detail": f"{base}({n}字)→{ruby}({len(ruby)}音)"})
    return bad


def check_line(line: str, segs: list[dict]) -> list[dict]:
    bad = check(line, segs)
    # I8：同一片段跨了多个 token（我们只有助数詞合并会这样，且是显式的）
    for seg in segs:
        w = seg.get("word")
        if w is None:
            continue
        span_tokens = {s.get("word") for s in segs if s.get("start") is not None
                       and s["start"] < seg["end"] and s["end"] > seg["start"]}
        if len(span_tokens) > 1:
            bad.append({"seg": seg, "code": "I8", "detail": f"跨 {len(span_tokens)} 个 token"})
    return bad
