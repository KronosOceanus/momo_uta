#!/usr/bin/env python3
"""规则检测：给定「原文 + gold spans」，判断这一句命中哪些规则（见 eval/rules.md）。

用途有两个：
  1. build_gold.py 分层抽样时给每句打规则标签
  2. eval.py 按规则分组出指标

设计原则：只用文本本身判断，不依赖分词器（评测脚本要能在没有 annotator 时也跑）。
所以这些检测器是**近似**的：宁可多标，不可漏标——多标只影响分层，不影响正确性判断。
"""

from __future__ import annotations

import re

# ---------------- 词表（v1 用少量内置，后续可换成 JMdict / 熟字訓表） ----------------

JUKUJIKUN = {
    "今日": ["きょう", "こんにち"], "昨日": ["きのう"], "明日": ["あす", "あした"],
    "大人": ["おとな"], "一人": ["ひとり"], "二人": ["ふたり"], "二十歳": ["はたち"],
    "眼鏡": ["めがね"], "田舎": ["いなか"], "相撲": ["すもう"], "土産": ["みやげ"],
    "風邪": ["かぜ"], "上手": ["じょうず", "うわて"], "下手": ["へた", "したて"],
    "今朝": ["けさ"], "一昨日": ["おととい"], "従兄弟": ["いとこ"], "黄昏": ["たそがれ"],
}

MULTI_READING = {
    "生": ["せい", "しょう", "なま", "い.きる", "う.まれる"],
    "上手": ["じょうず", "うわて"], "下手": ["へた", "したて"],
    "今日": ["きょう", "こんにち"], "空": ["そら", "あ.く", "から"],
    "前": ["まえ", "ぜん"], "後": ["あと", "うし.ろ", "ご"],
    "方": ["ほう", "かた"], "物": ["もの", "ぶつ"],
}

COUNTERS = "人日月年本枚匹台個回階時分秒円冊杯頭羽通件番号"

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")
KANA = re.compile(r"[\u3041-\u309f]")
KATAKANA = re.compile(r"[\u30a1-\u30f6]")
ASCII_ALNUM = re.compile(r"[0-9A-Za-z]")
DIGITS = re.compile(r"[0-9０-９]")
KANJI_DIGITS = re.compile(r"[一二三四五六七八九十百千万億]")
DAKUTEN = re.compile(r"[がぎぐげござじずぜぞだぢづでどばびぶべぼ]")
SOKUON = "っ"


def _labels_for_span(span: dict) -> set[str]:
    """单个 span 命中的规则"""
    base = span.get("base") or ""
    ruby = span.get("ruby") or ""
    hit: set[str] = set()

    kanji_n = len(KANJI.findall(base))
    if kanji_n >= 2:
        hit.add("R12")

    if base in JUKUJIKUN:
        hit.add("R4")
        if base in MULTI_READING:
            hit.add("R5")

    # 多音词：单字也命中
    if any(base == w or (w in base and len(w) >= 2) for w in MULTI_READING):
        hit.add("R5")

    # 数字 + 助数詞（span 可能只覆盖数字，所以词表判断放宽）
    if (DIGITS.search(base) or KANJI_DIGITS.search(base)) and any(c in base for c in COUNTERS):
        hit.add("R6")

    # 音便：促音便 / 連濁
    if SOKUON in ruby:
        hit.add("R3")
    elif DAKUTEN.search(ruby) and not DAKUTEN.search(base):
        # 单个汉字却出现浊音（花火 はなび 这类）——粗糙但够用
        if kanji_n == 1:
            hit.add("R3")

    # 当て字/造語：汉字数与 mora 数比例异常，且不在熟字訓表
    if base not in JUKUJIKUN:
        mora = len(re.sub(r"[^ぁ-んァ-ンー]", "", ruby))
        if kanji_n >= 1 and mora >= 2 * kanji_n + 3:
            hit.add("R8")

    return hit


def label_line(text: str, spans: list[dict]) -> dict:
    """给一行打规则标签。

    返回 {"rules": [...], "primary": "R4"}；primary 按优先级选，供分层用。
    """
    rules: set[str] = set()

    if KATAKANA.search(text):
        rules.add("R10")
    if ASCII_ALNUM.search(text):
        rules.add("R11")
    # R9：以假名为主、夹少量汉字（专门测 K 级直通与混排）
    kana_n = len(KANA.findall(text))
    han_n = len(KANJI.findall(text))
    if spans and kana_n >= 4 and kana_n >= 0.6 * (kana_n + han_n):
        rules.add("R9")
    # 数字 + 助数詞：在整句上判断（gold span 往往只覆盖数字本身）
    if re.search(r"[0-9０-９一二三四五六七八九十百千万億][" + COUNTERS + r"]", text):
        rules.add("R6")

    for sp in spans:
        rules |= _labels_for_span(sp)
        # R2：span 结束处后面紧跟假名（送り仮名）
        end = sp.get("end")
        if isinstance(end, int) and end < len(text) and KANA.match(text[end] or ""):
            rules.add("R2")

    # 固有名詞：粗略启发——两个以上汉字、读音不是常见音读模式、且长度≥4
    for sp in spans:
        base = sp.get("base") or ""
        if len(KANJI.findall(base)) >= 4:
            rules.add("R7")

    priority = ["R4", "R5", "R6", "R7", "R8", "R2", "R3", "R12", "R10", "R11", "R9", "R1"]
    primary = next((r for r in priority if r in rules), "R1")
    if not rules:
        rules.add("R1")

    return {"rules": sorted(rules), "primary": primary}
