#!/usr/bin/env python3
"""假名 → 罗马音 / IME 键位。

三层用途不同，规则不同，**不能混用**：

  罗马音  唱歌/朗读用。は(助詞)→wa、を→o、長音→同元音重复、っ→叠辅音
  键位    IME 键入用。は→ha、を→wo、ー→-、ん元音前→n'

都是纯查表 + 四条上下文规则，不涉及模型。
"""
from __future__ import annotations

import re

# ── 读音表（平假名 → 罗马音，ヘボン式 + 长音用 oo 风格）────────────
ROMAJI: dict[str, str] = {
    # 五十音
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o",
    "ん": "n",
    # 浊音 / 半浊音
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    # 拗音
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    # 外来音
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔ": "vu", "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
    "しぇ": "she", "じぇ": "je", "ちぇ": "che",
    "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
    # 小写（单独出现时）
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa",
}

# ── 键位表（假名 → 击键序列，取主流 IME 都接受的写法）────────────
KEYS: dict[str, str] = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "wo", "ん": "nn",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "di", "づ": "du", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "てぃ": "ti", "でぃ": "di", "うぃ": "wi", "うぇ": "we",
    "ゔ": "vu", "しぇ": "she", "じぇ": "je", "ちぇ": "che",
    # 罕见但表要全：小写单独、旧假名、拗音变体
    "ぁ": "xa", "ぃ": "xi", "ぅ": "xu", "ぇ": "xe", "ぉ": "xo",
    "ゃ": "xya", "ゅ": "xyu", "ょ": "xyo", "ゎ": "xwa",
    "ゐ": "wi", "ゑ": "we", "うぉ": "who", "とぅ": "twu", "どぅ": "dwu",
    "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
    "ぢゃ": "dya", "ぢゅ": "dyu", "ぢょ": "dyo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
}

VOWELS = set("aiueo")
KANA = re.compile(r"[ぁ-んゐゑゔ]")
SMALL_Y = set("ゃゅょ")
PARTICLES_WA = {"は": "wa", "へ": "e", "を": "o"}
TO_SOKUON = {"ch": "t", "ts": "t", "sh": "s", "j": "j"}


def to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def morae(kana: str) -> list[str]:
    """切成「假名单元」：拗音合成一个，っ/ー/ん 各一个。"""
    out: list[str] = []
    i = 0
    while i < len(kana):
        ch = kana[i]
        nxt = kana[i + 1] if i + 1 < len(kana) else ""
        if ch in "きしちにひみりぎじぢびぴふてでう" and nxt in SMALL_Y:
            out.append(ch + nxt)
            i += 2
            continue
        if ch in "ふてでうつ" and nxt in "ぁぃぇぉ":
            out.append(ch + nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return out


def _vowel_of(romaji: str) -> str:
    for ch in reversed(romaji):
        if ch in VOWELS:
            return ch
    return ""


def _units_romaji(units: list[str], particle: bool = False, whole: str = "") -> list[str]:
    """逐单元罗马音；和 units 等长，拼接即为整词。っ 取下一个单元的辅音。"""
    out: list[str] = []
    prev = ""
    for i, unit in enumerate(units):
        if unit == "っ":
            nxt = units[i + 1] if i + 1 < len(units) else ""
            nxt_r = ROMAJI.get(nxt, "")
            head = next((TO_SOKUON[p] for p in ("ch", "ts", "sh") if nxt_r.startswith(p)), "")
            out.append(head or (nxt_r[:1] if nxt_r[:1] not in VOWELS else "tsu"))
            prev = ""
            continue
        if unit == "ー":
            out.append("-")          # 长音符按字面写 -（和键位一致）
            prev = ""
            continue
        r = ROMAJI.get(unit)
        if r is None:
            out.append("■")
            prev = ""
            continue
        out.append(r)
        prev = r
    return out


def romaji_of(kana: str, particle: bool = False) -> str:
    """假名 → 罗马音。**完全逐字转写**：きょう→kyou、コーヒー→ko-hi-。"""
    kana = to_hira(kana)
    if particle and kana in PARTICLES_WA:
        return PARTICLES_WA[kana]
    return "".join(_units_romaji(morae(kana)))


def romaji_pieces(kana: str, particle: bool = False) -> list[str]:
    """按假名单元切开，返回与 morae(kana) 等长的罗马音片段。"""
    kana = to_hira(kana)
    if particle and kana in PARTICLES_WA:
        return [PARTICLES_WA[kana]]
    return _units_romaji(morae(kana))


def keys_pieces(kana: str) -> list[str]:
    """按假名单元切开，返回与 morae(kana) 等长的键位片段。"""
    units = morae(to_hira(kana))
    out: list[str] = []
    for i, unit in enumerate(units):
        if unit == "ー":
            out.append("-")
            continue
        if unit == "っ":
            nxt = KEYS.get(units[i + 1], "") if i + 1 < len(units) else ""
            head = next((TO_SOKUON[p] for p in ("ch", "ts", "sh") if nxt.startswith(p)), "")
            out.append(head or (nxt[:1] if nxt else "xtsu"))
            continue
        if unit == "ん":
            nxt = KEYS.get(units[i + 1], "") if i + 1 < len(units) else ""
            out.append("n'" if nxt and nxt[:1] in "aeiouy" else "n")
            continue
        out.append(KEYS.get(unit, "■"))
    return out


def keys_of(kana: str) -> str:
    """假名 → 击键序列。ん 在元音/や行前写 n'，ー 写 -，っ 叠下一个辅音。"""
    kana = to_hira(kana)
    units = morae(kana)
    out: list[str] = []
    for i, unit in enumerate(units):
        if unit == "ー":
            out.append("-")
            continue
        if unit == "っ":
            nxt = KEYS.get(units[i + 1], "") if i + 1 < len(units) else ""
            for prefix in ("ch", "ts", "sh"):
                if nxt.startswith(prefix):
                    out.append(TO_SOKUON[prefix])
                    break
            else:
                out.append(nxt[:1] if nxt else "xtsu")
            continue
        if unit == "ん":
            nxt = KEYS.get(units[i + 1], "") if i + 1 < len(units) else ""
            out.append("n'" if nxt and nxt[:1] in "aeiouy" else "n")
            continue
        out.append(KEYS.get(unit, "■"))
    return "".join(out)
