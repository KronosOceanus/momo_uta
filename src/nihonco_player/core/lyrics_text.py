#!/usr/bin/env python3
"""歌词文本层：LRC 解析、名字清洗与匹配、语言判定、排除词。不联网、不写盘。"""
from __future__ import annotations

import json
import re
import unicodedata

from nihonco_yomi.config import LY as CFG
from nihonco_yomi.paths import ROOT

JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
TIMED = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)(?:-\d+)?\](.*)$", re.MULTILINE)
KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
HAN = re.compile(r"[\u4e00-\u9fff]")


LRC = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)(?:-\d+)?\](.*)$")   # 兼容 [00:12.34-1]
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
LAT_RE = re.compile(r"[A-Za-z]")


def has_timed(lrc: str) -> bool:
    """整段里是否至少有一行带时间戳（多行文本必须能匹配）。"""
    return any(TIMED.match(line.strip()) for line in str(lrc or "").splitlines())


def content_lines(lrc: str) -> int:
    """真正有内容的歌词行数（排除只有作词/作曲的元数据行）。"""
    n = 0
    for ln in (lrc or "").splitlines():
        m = TIMED.match(ln.strip())
        if not m:
            continue
        body = m.group(3).strip()
        if body and not META.match(body):
            n += 1
    return n


def lang_guess(lrc: str) -> tuple[str, float]:
    """按歌词假名占比判断语言：≥10% 日语，<3% 非日语，中间空白带。"""
    body = "\n".join(ln.split("]", 1)[-1] for ln in (lrc or "").splitlines())
    k, h = len(KANA.findall(body)), len(HAN.findall(body))
    if k + h < CFG["lang_min_chars"]:
        return "unknown", 0.0
    r = k / (k + h)
    return ("ja" if r >= CFG["kana_ratio_min"] else "other"), round(r, 3)
def kind(s: str) -> str:
    k, h, l = len(KANA_RE.findall(s)), len(HAN_RE.findall(s)), len(LAT_RE.findall(s))
    tot = k + h + l
    if tot == 0:
        return "other"
    if k and k / tot > 0.15:
        return "ja"
    if h > l:
        return "zh"
    return "en" if l else "other"


PUNCT = re.compile(r"[\s\-–—~〜!！?？\.。、,，()（）\[\]【】「」『』:：/／'\"’”·・]")


def _norm(s: str) -> str:
    # NFKC 先归一（浊点合成/分解、全半角），否则"やなぎなぎ"两种写法会被当成两个名字
    return PUNCT.sub("", unicodedata.normalize("NFKC", s or "").lower())


def _match(want: str, got: str) -> bool:
    """歌名匹配：完全相等，或（较长的一方）包含另一方。
    短标题不再做子串匹配——否则 Dot Brain 会命中 レイン。"""
    a, b = _norm(want), _norm(got)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= CFG["name_min_len"] and short in long_


def clean_artist(a: str) -> str:
    """"甲,乙,甲乙" 这种重复拼接的歌手名压成 "甲,乙"。"""
    parts = [x.strip() for x in re.split(r"[,、/&]", a or "") if x.strip()]
    out: list[str] = []
    for x in parts:
        if x in out:
            continue
        # "甲乙" 只是前面几个人的拼接 → 丢掉
        if len(out) >= 2 and x == "".join(out):
            continue
        out.append(x)
    return ",".join(out)


def split_name(stem: str) -> tuple[str, str]:
    p = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(p) == 2:
        return clean_artist(p[0].strip()), p[1].strip()
    return "", stem.strip()


def is_likely_song(stem: str) -> bool:
    body = stem.split(" - ")[-1]
    return not BGMA.search(stem) and not BGMT.search(body)


META = re.compile(r"^\s*(作词|作曲|编曲|制作|演唱|作詞|編曲|Lyricist|Composer|Arranger|Producer)")
EXCLUDE_FILE = ROOT / "data" / "curated" / "lyrics_exclude.json"


def _exclude_patterns() -> list[str]:
    try:
        return [x.lower() for x in json.loads(EXCLUDE_FILE.read_text(encoding="utf-8")).get("patterns", [])]
    except Exception:
        return []


_PATTERNS = None


def is_excluded(name: str) -> bool:
    """歌名/歌词名里含伴奏、卡拉OK 之类 → 排除。"""
    global _PATTERNS
    if _PATTERNS is None:
        _PATTERNS = _exclude_patterns()
    n = _norm(name)
    return any(_norm(x) in n for x in _PATTERNS)
BGMA = re.compile(r"梶浦|阿保|光宗|安瀬|尾澤|金子憲次|Active Planets|Dungeon|HOYO|V\.K")
BGMT = re.compile(r"^(M\d+|.*(theme|Theme|Piano|Instrumental|inst|BGM|bgm|Remix|arrange))")
