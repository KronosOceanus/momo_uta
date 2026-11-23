#!/usr/bin/env python3
"""青空文庫の注記形式を解析して「本文 + ルビ区間」に分解する。

対応する記法（JIS X 4081 / 青空文庫 注記形式）:

    ｜親文字《ルビ》      明示的な範囲指定
    親文字《ルビ》        直前の漢字連続を親文字とみなす
    ［＃…］              注記（除去）
    ※［＃…］            外字注記（除去）
    <ruby>漢<rt>かん</rt></ruby>   新しめの XHTML 版（先に《》へ正規化）

出力:
    plain : ルビ記号を除いた本文（HTML タグも除去済み）
    spans : [{"start", "end", "base", "ruby"}]  start/end は plain 上の文字オフセット

注意:
    - ルビは通常カタカナなので、ひらがなへ変換して返す
    - 返す base は必ず plain[start:end] と一致する（不変条件）
"""

from __future__ import annotations

import re

from momo_yomi.kana import kata_to_hira

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")   # 漢字 + 々 + 〆
NOTE = re.compile(r"※?［＃.*?］", re.S)
HTML_TAG = re.compile(r"<[^>]+>")
RUBY_TAG = re.compile(r"<ruby>(.*?)</ruby>", re.S | re.I)
RT_TAG = re.compile(r"<rt[^>]*>(.*?)</rt>", re.S | re.I)
RUBY_BASE = re.compile(r"<rb[^>]*>(.*?)</rb>", re.S | re.I)



def _ruby_tags_to_notation(text: str) -> str:
    """<ruby>漢<rt>かん</rt></ruby> → ｜漢《かん》"""
    def repl(m):
        inner = m.group(1)
        rt = RT_TAG.search(inner)
        if not rt:
            return inner
        base = RUBY_BASE.search(inner)
        if base:
            b = base.group(1)
        else:
            b = RT_TAG.sub("", inner)
        return f"｜{b}《{rt.group(1)}》"
    return RUBY_TAG.sub(repl, text)


def parse(text: str) -> tuple[str, list[dict]]:
    """注記テキスト → (plain, spans)。base は必ず plain[start:end] と一致する。"""
    text = _ruby_tags_to_notation(text)
    text = NOTE.sub("", text)
    text = HTML_TAG.sub("", text)

    out: list[str] = []
    spans: list[dict] = []
    pending: int | None = None       # ｜ の位置（out 上のインデックス）
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == "｜":
            pending = len(out)
            i += 1
            continue

        if ch == "《":
            close = text.find("》", i + 1)
            if close < 0:                      # 閉じがない → そのまま
                out.append(ch)
                i += 1
                continue
            ruby = kata_to_hira(text[i + 1:close].strip())
            if pending is not None:
                start = pending
            else:
                start = len(out)
                while start > 0 and KANJI.match(out[start - 1]):
                    start -= 1
            base = "".join(out[start:])
            if base and ruby:
                spans.append({"start": start, "end": len(out), "base": base, "ruby": ruby})
            pending = None
            i = close + 1
            continue

        out.append(ch)
        i += 1

    return "".join(out), spans


def check(text: str, spans: list[dict]) -> list[str]:
    """不変条件の検証。壊れていたら理由のリストを返す（空なら OK）。"""
    errs = []
    for s in spans:
        if text[s["start"]:s["end"]] != s["base"]:
            errs.append(f"base 不一致: {s}")
        if not s["ruby"]:
            errs.append(f"ruby が空: {s}")
        if not any(KANJI.match(c) for c in s["base"]):
            errs.append(f"base に漢字がない: {s}")
    return errs
