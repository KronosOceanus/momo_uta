#!/usr/bin/env python3
"""数字 + 助数詞：表装载、读音计算、片段合并。

表在 data/curated/counters.json（词表，不是规则）；这里只有装载和查表。
"""
from __future__ import annotations


COUNTERS: dict = {}
NUM_TSITSU: dict = {}       # 一〜十 + つ
NUM_NIN: dict = {}          # 一人 / 二人 / 四人
COUNTER_EXPLICIT: dict = {} # 数字逐个写死的（人 / 羽）
COUNTER_IRREGULAR: dict = {}# 音便（回 / 歳 / 本 / 匹 / 杯 / 階）
COUNTER_TWEAK: dict = {}    # 月 / 時：数字和助数词分开读
COUNTER_REGULAR: dict = {}  # 一般助数词
NUM_KANJI: dict = {}
BASE_READING: dict = {}

NUM_KANJI_SET = set("一二三四五六七八九十百千万億零〇")
NUM_CHARS = NUM_KANJI_SET | set("０１２３４５６７８９")


def load_counters(raw: dict) -> None:
    """把 counters.json 装成运行期结构（JSON 的键是字符串，数字键要转回来）。"""
    global NUM_TSITSU, NUM_NIN, COUNTER_EXPLICIT, COUNTER_IRREGULAR, COUNTER_TWEAK
    global COUNTER_REGULAR, NUM_KANJI, BASE_READING
    NUM_TSITSU = dict(raw.get("tsitsu") or {})
    NUM_NIN = dict(raw.get("nin") or {})
    COUNTER_EXPLICIT = {k: {int(n): r for n, r in v.items()} for k, v in (raw.get("explicit") or {}).items()}
    COUNTER_IRREGULAR = {k: {int(n): r for n, r in v.items()} for k, v in (raw.get("irregular") or {}).items()}
    COUNTER_TWEAK = {k: ({int(n): r for n, r in v["special"].items()}, v["tail"])
                     for k, v in (raw.get("tweak") or {}).items()}
    COUNTER_REGULAR = dict(raw.get("regular") or {})
    NUM_KANJI = {k: int(v) for k, v in (raw.get("num_kanji") or {}).items()}
    BASE_READING = {int(k): v for k, v in (raw.get("base_reading") or {}).items()}
    COUNTERS.clear()
    COUNTERS.update(raw)


def parse_number(s: str) -> int | None:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        n = int(s)
        return n if 0 < n <= 99 else None
    if s == "十":
        return 10
    if len(s) == 1 and s in NUM_KANJI:
        return NUM_KANJI[s]
    if len(s) == 2 and s[0] == "十" and s[1] in NUM_KANJI:
        return 10 + NUM_KANJI[s[1]]
    if len(s) == 2 and s[1] == "十" and s[0] in NUM_KANJI:
        return NUM_KANJI[s[0]] * 10
    return None


def counter_reading(num: int, counter: str) -> str | None:
    if counter in COUNTER_EXPLICIT and num in COUNTER_EXPLICIT[counter]:
        return COUNTER_EXPLICIT[counter][num]
    if counter in COUNTER_IRREGULAR and num in COUNTER_IRREGULAR[counter]:
        return COUNTER_IRREGULAR[counter][num]
    base = BASE_READING.get(num)
    if base is None:
        return None
    if counter == "人":
        return base + "にん"
    if counter in COUNTER_REGULAR:
        return base + COUNTER_REGULAR[counter]
    if counter in COUNTER_IRREGULAR:
        return base + {"歳": "さい", "回": "かい"}.get(counter, "ほん")
    return None


def merge_counters(line: str, segs: list[dict]) -> list[dict]:
    """把「数字 token + 助数詞 token」合成一段，用助数詞表给读音。

    分词器会切成 一 + 羽、八 + 月、2 + 人，单看每个 token 都得不到正确读法。
    """
    out: list[dict] = []
    i = 0
    while i < len(segs):
        cur = segs[i]
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if nxt and cur["base"] and all(ch in NUM_CHARS for ch in cur["base"]):
            if nxt["base"] == "日":
                # 日期(ついたち/みっか)还是天数(いちにち/さんにち)，字形看不出来。
                # 有候选但选不定 → 标出来，降级到 B（不合并，保留分词器的读法）
                out.append({**cur, "level": "B", "basis": "数词+日（日期/天数两读）"})
                out.append({**nxt, "level": "B", "basis": "数词+日（日期/天数两读）"})
                i += 2
                continue
            tweak = COUNTER_TWEAK.get(nxt["base"])
            num0 = parse_number(cur["base"]) if len(nxt["base"]) == 1 else None
            if tweak and num0:
                special, tail = tweak
                head = special.get(num0) or BASE_READING.get(num0)
                if head:
                    out.append({**cur, "ruby": head, "level": "A", "source": "counter", "basis": "助数詞表"})
                    out.append({**nxt, "ruby": tail, "level": "A", "source": "counter", "basis": "助数詞表"})
                    i += 2
                    continue
            counter = nxt["base"]
            if len(counter) == 1 and counter in (set(COUNTER_EXPLICIT) | set(COUNTER_IRREGULAR) | set(COUNTER_REGULAR)):
                num = parse_number(cur["base"])
                reading = counter_reading(num, counter) if num else None
                if reading and nxt["end"] == cur["end"] + 1:
                    out.append({"base": line[cur["start"]:nxt["end"]],
                                "start": cur["start"], "end": nxt["end"],
                                "word": cur.get("word"),
                                "ruby": reading, "level": "A", "source": "counter", "basis": "助数詞表"})
                    i += 2
                    continue
        out.append(cur)
        i += 1
    return out


# ── 数字本身的读法（引擎常读错：33 → サンサン）────────────────────
_BASE = {1: "いち", 2: "に", 3: "さん", 4: "よん", 5: "ご",
         6: "ろく", 7: "なな", 8: "はち", 9: "きゅう"}
_HYAKU = {1: "ひゃく", 3: "さんびゃく", 6: "ろっぴゃく", 8: "はっぴゃく"}
_SEN = {1: "せん", 3: "さんぜん", 8: "はっせん"}


def numeral_reading(n: int) -> str | None:
    """阿拉伯数字的日语读法（0–9999）。规则是封闭的，不需要查表。"""
    if n == 0:
        return "れい"
    if not 0 < n < 10000:
        return None
    parts: list[str] = []
    sen, rest = divmod(n, 1000)
    if sen:
        parts.append(_SEN.get(sen) or _BASE[sen] + "せん")
    hyaku, rest = divmod(rest, 100)
    if hyaku:
        parts.append(_HYAKU.get(hyaku) or _BASE[hyaku] + "ひゃく")
    juu, ichi = divmod(rest, 10)
    if juu:
        parts.append(("" if juu == 1 else _BASE[juu]) + "じゅう")
    if ichi:
        parts.append(_BASE[ichi])
    return "".join(parts)
