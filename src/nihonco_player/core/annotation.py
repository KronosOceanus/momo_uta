#!/usr/bin/env python3
"""注音装配：引擎结果 → 播放器/文件需要的形状。

从 service/song.py 抽出来，纯函数、无 HTTP、无文件 IO。
三处共用：载荷装配、改读音、保存时重新注音。
"""
from __future__ import annotations

import re

import nihonco_yomi
from nihonco_yomi.render import segments_html, words_html

from . import diag

AN = nihonco_yomi.Annotator()

RUBY_PAREN = re.compile(r"([\u4e00-\u9fff]+)[（(]([ぁ-んー]+)[）)]")


def ruby_html(result) -> str:
    return segments_html(result["lines"][0]["segments"], candidates=True, editable_ab=True)


def words_html_of(result, key: str = "romaji") -> str:
    return words_html(result["lines"][0]["segments"], key)


def strip_paren_ruby(text: str) -> tuple[str, dict]:
    """LRC 里常写成 笑顔(かお)——括号里是实际唱的読み。
    去掉括号，把它记成 override（按"去掉后"的字面位置换算）。"""
    notes = {}
    clean = text
    while True:
        m = RUBY_PAREN.search(clean)
        if not m:
            break
        notes[m.start()] = m.group(2)
        clean = clean[:m.start()] + m.group(1) + clean[m.end():]
    return clean, notes


def _stored_overrides(clean: str, segs: list, stored: list) -> dict | None:
    """把文件里的 [base,ruby,lv] 对齐到引擎片段；对不上返回 None（标注已过期）。"""
    ov, pos = {}, 0
    for item in stored:
        base, ruby = item[0], (item[1] if len(item) > 1 else None)
        if not base:
            return None
        seg = next((x for x in segs if x.get("start") == pos), None)
        if not seg or seg.get("base") != base:
            return None
        if ruby and ruby != (seg.get("ruby") or ""):
            ov[f"o:0-{seg['word']}"] = ruby
        pos += len(base)
    return ov if pos == len(clean) else None


def annotate_line_with_notes(text: str, extra_start: int | None = None,
                             extra_reading: str | None = None,
                             stored: list | None = None) -> dict:
    """标一行：先处理行内注音 笑顔(かお)，再叠加用户改的那一处 / 文件里的标注。

    text 必须是"清洗前"的原文（含括号写法），这样调用方拿到的 start
    与渲染出来的偏移一致。
    """
    clean, notes = strip_paren_ruby(text)
    base = AN.annotate(clean)
    segs = base["lines"][0]["segments"]
    ov = {}
    for start, kana in notes.items():
        seg = next((x for x in segs if x["start"] == start), None)
        if seg:
            ov[f"o:0-{seg['word']}"] = kana
    if extra_start is not None and extra_reading:
        seg = next((x for x in segs if x["start"] == extra_start), None)
        if seg:
            ov[f"o:0-{seg['word']}"] = extra_reading
    if stored:
        got = _stored_overrides(clean, segs, stored)
        if got is not None:
            ov.update({k: v for k, v in got.items() if v})
    return AN.annotate(clean, ov) if ov else base


def segs_of(result) -> list:
    """引擎结果 → 文件里存的紧凑形式 [[base, ruby, level], …]"""
    return [[seg["base"], seg.get("ruby"), seg.get("level")]
            for seg in result["lines"][0]["segments"]]


def annotations_from_lines(lines: list[dict]) -> dict[int, list]:
    """按当前行内容重新注音，生成 nhlrc 的标注表。"""
    out: dict[int, list] = {}
    for i, ln in enumerate(lines):
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        try:
            out[i] = segs_of(annotate_line_with_notes(text))
        except Exception as e:
            diag.log("annotate", f"行 {i} 注音失败：{e}")
    return out


def line_fields(text: str, stored: list | None = None) -> dict:
    """一行文本 → 载荷字段（ruby HTML / 罗马音 / 键位 / 分行高亮）。"""
    r = annotate_line_with_notes(text, stored=stored)
    return {"ruby": ruby_html(r), "rm": r.get("romaji", {}).get("text", ""),
            "ky": r.get("keys", {}).get("text", ""),
            "rmH": words_html_of(r, "romaji"), "kyH": words_html_of(r, "keys")}
