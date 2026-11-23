#!/usr/bin/env python3
"""日语标注服务。M1：接入 MeCab(UniDic)，A 级只给「单候选、非专名、非数词」。

契约（docs/service-design.md §5.4）：
    请求  {"text","layers","options"}
    响应  {"version","lines","stats"}

分段策略：
    每个 token 按「假名前后缀 / 汉字核心」切成多个 segment，
    这样 ruby 只覆盖汉字部分（食(た)べる → [食|た] + [べる]），
    与 gold 的区间口径一致，评测才能按区间重叠比较。

级别：
    A  含汉字、有读音、非专名/数词、不在多音词表
    K  纯假名片段（本来就没有可注的）
    C  其余：专名、数词、多音词、读音缺失

用法:
    python3 -m momo_yomi.annotate --stdio
    python3 -m momo_yomi.annotate --text "今日は雨が降る"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from dataclasses import dataclass, field

from .kana import kata_to_hira
from .invariants import check_line as check_invariants
from .thresholds import MIN_CORPUS_N, SINGLE_READING_SHARE
from . import counters

from .common import CORPUS, CURATED, TABLES as TABLE_DIR


@dataclass
class Tables:
    """表分两类：判定用的（每次都载）和 LLM 候选用的（--llm 才载）。"""

    # 判定用
    heteronym: dict = field(default_factory=dict)     # 多音字 3614（分档兜底）
    candidates: dict = field(default_factory=dict)    # 所有 ≥2 读音的词（列候选用）
    stats: dict = field(default_factory=dict)         # 语料读音分布（A/AB/B 的依据）
    # --llm 才载
    readings: dict = field(default_factory=dict)
    common: dict = field(default_factory=dict)
    loaded: bool = False


LEVEL_RANK = {"A": 0, "AB": 1, "B": 2, "C": 3}


@dataclass
class Config:
    oov_mode: str = "abstain"   # abstain（弃权）/ mark（标成 B）
    disable: set = field(default_factory=set)   # 诊断用：关掉某些表/规则
    emit: str = "B"          # 只输出到这一档为止（A < AB < B），政策层，不参与判定
    llm: bool = False
    min_conf: float = 0.0
    keep_ruby: bool = False
    llm_choices: dict = field(default_factory=dict)


TABLES = Tables()
CONFIG = Config()


def load_tables(force: bool = False) -> None:
    """加载词典表。重复调用不会重复读盘。"""
    if TABLES.loaded and not force:
        return
    # 缺表 = 规则失效但输出看起来正常 → 直接报错，不静默
    required = {
        "jmdict_heteronym.json": "heteronym",
    }
    for fname, attr in required.items():
        fp = TABLE_DIR / fname
        if not fp.exists():
            raise RuntimeError(f"缺表：{fp}（判定依赖它，不能用空表继续）")
        setattr(TABLES, attr, json.loads(fp.read_text(encoding="utf-8")))

    cp = TABLE_DIR / "jmdict_candidates.json"
    if cp.exists():
        TABLES.candidates = json.loads(cp.read_text(encoding="utf-8"))

    gp = CURATED / "glossary_lyrics.json"
    if not gp.exists():
        raise RuntimeError(f"缺表：{gp}（人工词表）")
    GLOSSARY.update(json.loads(gp.read_text(encoding="utf-8")))

    counters_path = CURATED / "counters.json"
    if not counters_path.exists():
        raise RuntimeError(f"缺表：{counters_path}（助数詞表）")
    counters.load_counters(json.loads(counters_path.read_text(encoding="utf-8")))

    stp = CORPUS / "ndl_reading_stats.json"
    if stp.exists():
        TABLES.stats = json.loads(stp.read_text(encoding="utf-8"))

    if CONFIG.llm:
        TABLES.readings = json.loads((TABLE_DIR / "jmdict_readings.json").read_text(encoding="utf-8"))
        cp = TABLE_DIR / "jmdict_common_readings.json"
        if cp.exists():
            TABLES.common = json.loads(cp.read_text(encoding="utf-8"))
        from llm import load_cache
        CONFIG.llm_choices = load_cache()
    TABLES.loaded = True



KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")
NUMERALS = set("一二三四五六七八九十百千万億零〇１２３４５６７８９０0123456789")

# data/curated/glossary_lyrics.json：人工确认的读音（**只为歌词领域调过**）
# 适配范围：**J-Pop 歌词**（人称代词在歌词里几乎总读口语形）。
# 文件名带 _lyrics 就是这个意思：换领域（商务文书/古典）要另建一张，不要改这张。
# 正式文书里「私」读 わたくし，这里会被强制成 わたし——不是通用规则。
GLOSSARY: dict[str, str] = {}
KANA_TAIL = re.compile(r"[ぁ-ん]+$")
KANA_HEAD = re.compile(r"^[ぁ-ん]+")

VERSION = {"engine": "sudachi", "dict": "sudachidict_core", "service": "0.3.0"}
_TAGGER = None
_INIT_LOCK = threading.Lock()
_TOKEN_LOCK = threading.Lock()


class _SudachiWord:
    """Sudachi 形态素，投影成判定链用的字段（surface / feature / is_oov）。"""

    __slots__ = ("surface", "feature", "is_oov")

    def __init__(self, m):
        self.surface = m.surface()
        self.is_oov = bool(m.is_oov())
        pos = list(m.part_of_speech())          # (品詞, 細分類1, 2, 3, 活用型, 活用形)
        reading = m.reading_form()              # 片假名
        lemma = m.dictionary_form()
        # 判定链用到的位置：0-3 词性、6 读音、7 原形、8 出现形、10 表记
        self.feature = (pos[0], pos[1], pos[2], pos[3], "*", "*",
                        reading, lemma, self.surface, reading, self.surface)


class _SudachiTagger:
    def __init__(self):
        from sudachipy import dictionary
        self._tok = dictionary.Dictionary().tokenizer(mode="A")

    def __call__(self, text: str):
        # Sudachi 的 Tokenizer 不能并发使用（HTTP 是多线程的）
        with _TOKEN_LOCK:
            # Sudachi 会在行尾吐零长 token（预分词副作用），跳过
            return [_SudachiWord(m) for m in self._tok.tokenize(text) if m.surface()]


def get_tagger():
    """Sudachi 惰性加载。缺依赖直接报错，不静默退化。"""
    global _TAGGER
    if _TAGGER is None:
        with _INIT_LOCK:
            if _TAGGER is None:
                try:
                    _TAGGER = _SudachiTagger()
                except ImportError as e:
                    raise RuntimeError("没装 sudachipy；装：pip install -r requirements.txt") from e
    return _TAGGER


KANJI_RUN = re.compile(r"[\u4e00-\u9fff\u3005\u3006]+")
KANA_RUN = re.compile(r"[ぁ-ん]+")
KATAKANA_RUN = re.compile(r"[ァ-ヶー]+")
DIGIT_RUN = re.compile(r"[0-9０-９]")


def occ_reading(feat) -> str:
    """读音：Sudachi 的 reading_form 就是出现形读音，直接转平假名。"""
    try:
        return kata_to_hira(str(feat[6] or ""))
    except Exception:
        return ""


def split_pieces(surface: str, reading_hira: str) -> list[tuple[str, str | None]] | None:
    """把 token 切成 [(文本, 读音或 None)]，读音只覆盖汉字块。

    用 DP 求**消耗掉整个读音**的切法：假名块必须逐字对上，汉字块吃 ≥1 个音节。
    不能贪心地找"第一个出现的假名"——恋煩い(こいわずらい) 里的「い」会出现两次，
    贪心会切出 (恋煩,こ) 并把 わずら 丢掉，这正是静默失败（读音对、对齐错）。

    例：
        食べる   たべる   → [("食","た"), ("べる",None)]
        恋煩い   こいわずらい → [("恋煩","こいわずら"), ("い",None)]
        お茶     おちゃ    → [("お",None), ("茶","ちゃ")]
    """
    chunks = re.findall(
        r"[\u4e00-\u9fff\u3005\u3006０-９0-9]+"   # 汉字 / 数字（2人、1番）
        r"|[ぁ-ん]+|[ァ-ヶー]+"                      # 平假名 / 片假名（満タン）
        r"|[^\u4e00-\u9fff\u3005\u3006０-９0-9ぁ-んァ-ヶー]+", surface)
    if not chunks:
        return None

    n, m = len(chunks), len(reading_hira)
    is_kana = [bool(KANA_RUN.fullmatch(c) or KATAKANA_RUN.fullmatch(c)) for c in chunks]
    # 数字块当"要读音的块"处理（33 → さんじゅうさん）
    is_kanji = [bool(KANJI_RUN.search(c) or DIGIT_RUN.search(c)) for c in chunks]
    memo: dict[tuple[int, int], bool] = {}

    def ok(i: int, pos: int) -> bool:
        if i == n:
            return pos == m
        key = (i, pos)
        if key in memo:
            return memo[key]
        ch = chunks[i]
        res = False
        if not is_kanji[i]:
            # 假名块（含片假名）/ 其他字符：必须逐字对上
            piece = kata_to_hira(ch) if is_kana[i] else ch
            res = reading_hira.startswith(piece, pos) and ok(i + 1, pos + len(piece))
        else:
            klen = sum(len(x) for x in KANJI_RUN.findall(ch)) + sum(1 for c in ch if c.isdigit() or c in "０１２３４５６７８９")
            for take in range(max(1, klen), 4 * klen + 1):
                if pos + take <= m and ok(i + 1, pos + take):
                    res = True
                    break
        memo[key] = res
        return res

    if not ok(0, 0):
        return None

    out: list[tuple[str, str | None]] = []
    i = pos = 0
    while i < n:
        ch = chunks[i]
        if not is_kanji[i]:
            out.append((ch, None))
            pos += len(ch)
        else:
            klen = sum(len(x) for x in KANJI_RUN.findall(ch)) + sum(1 for c in ch if c.isdigit() or c in "０１２３４５６７８９")
            for take in range(max(1, klen), 4 * klen + 1):
                if pos + take <= m and ok(i + 1, pos + take):
                    out.append((ch, reading_hira[pos:pos + take]))
                    pos += take
                    break
        i += 1
    return out


def candidates_for(key: str) -> list[str]:
    """候选读音：词典 + 语料 + 多音字表，**按语料里出现的次数从高到低排**。

    排序依据是 stats 的分布；没有统计的排在后面（字典序）。
    """
    rs = set(TABLES.common.get(key) or TABLES.readings.get(key) or [])
    rs |= set(TABLES.heteronym.get(key) or [])
    rs |= set(TABLES.candidates.get(key) or [])
    st = TABLES.stats.get(key)
    dist = {}
    if st:
        rs.add(st["top"])
        dist = {r: c for r, c in (st.get("dist") or {}).items()}
    n_kanji = max(1, len(KANJI_RUN.findall(key)))
    out, seen = [], set()
    for r in rs:
        if not r or not all("ぁ" <= ch <= "ん" or ch == "ー" for ch in r):
            continue
        if not (1 <= len(r) <= 4 * n_kanji):      # 摩拉数 sanity，挡掉 赤→あかんぼう 这类噪声
            continue
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    out.sort(key=lambda r: (-dist.get(r, 0), r))
    return out[:8]


def cache_key(line: str, start: int, base: str, cands: list[str]) -> str:
    import hashlib
    raw = f"{line}\u0000{start}\u0000{base}\u0000{'|'.join(cands)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]



def why(code: str, label: str, **extra) -> dict:
    """结构化的弃权理由：code 给程序用，label 给人看。"""
    return {"code": code, "label": label, **extra}


def _word_decision(surface: str, reading: str, key: str, pos: str,
                   oov_flag: bool | None = None) -> dict:
    """整词的判定：只说"这个读音是怎么来的"，不说档位。

    档位由 assign_level() 统一算，避免同一个概念散落在三处。
    """
    # R2 人工钉死（确定：显式覆盖，不做推断）
    forced = GLOSSARY.get(key)
    if forced and surface == key and "glossary" not in CONFIG.disable:
        return {"source": "forced"}

    # R6 OOV 闸门：引擎自己说了算（Sudachi 用 is_oov，UniDic 用 JMdict 词表）
    is_oov = bool(oov_flag)
    # 数字：Sudachi 标成 OOV，但读音取决于后面接什么（一→いち/ひと/ひとつ）→ 标 B
    if all(ch in NUMERALS for ch in surface):
        return {"source": "numeral"}
    if is_oov:
        # 带送り仮名、且汉字读音能和假名对齐 → 是被并成一词的活用词（帰りゆく）
        if re.search(r"[ぁ-ん]", surface) and split_pieces(surface, reading) is not None:
            return {"source": "dict"}
        if CONFIG.oov_mode == "mark":
            return {"source": "oov_marked"}
        return {"source": "dict", "abstain": why("oov", "OOV（词表里没有）")}

    # R7 固有名詞：读音不可推，但有词典读音 → 标成 B（淡色），不弃权
    if "固有名詞" in set((pos or "").split("/")):
        return {"source": "proper"}

    return {"source": "dict"}


def assign_level(source: str, key: str, reading: str) -> tuple[str, str]:
    """唯一的档位判定点。返回 (level, basis)，basis 说明凭什么这么定。

    A  人工确认，或词典单读音（语料证明只有一个读音）
    AB 多音字里我们选的和语料主读一致；熟字訓表命中
    B  多音字但选的和语料主读不符，或没有语料证据
    """
    if source == "forced":
        return "A", "人工词表"
    if source == "counter":
        return "A", "助数詞表"
    if source == "oov_marked":
        return "B", "OOV（引擎不认识，读音不确定）"
    if source == "proper":
        return "B", "固有名詞（读音不可推）"
    if source == "numeral":
        return "B", "数字（读音取决于后接的助数詞）"

    st = TABLES.stats.get(key)
    if st and st.get("n", 0) >= MIN_CORPUS_N:
        if st["share"] >= SINGLE_READING_SHARE:
            return "A", f'语料单读 {st["share"]:.0%}（n={st["n"]}）'
        top = kata_to_hira(st["top"])
        r = kata_to_hira(reading)
        if r and (r == top or r.startswith(top) or top.startswith(r)):
            return "AB", f'与语料主读一致（{st["top"]}, n={st["n"]}）'
        return "B", f'与语料主读不符（主读 {st["top"]}）'
    if "heteronym" not in CONFIG.disable and key in TABLES.heteronym:
        return "B", "多音字（无语料证据）"
    return "A", "词典单读音"


def annotate_token(w, line: str = "", start: int = -1) -> list[dict]:
    """把一个 token 变成若干 segment（相对偏移由调用方平移）。"""
    surface = w.surface
    feat = w.feature
    pos = "/".join(str(x) for x in feat[:4] if x and x != "*")

    try:
        reading = occ_reading(feat) or str(feat[6] or "")
    except Exception:
        reading = ""
    reading_hira = kata_to_hira(reading) if reading and reading != "*" else ""

    if not KANJI_RUN.search(surface) and not all(ch in NUMERALS for ch in surface):
        return [{"text": surface, "ruby": None, "level": "K", "pos": pos}]
    if not reading_hira:
        return [{"text": surface, "ruby": None, "level": "C",
                 "reason": why("no_reading", "无读音")}]

    pieces = split_pieces(surface, reading_hira)
    if pieces is None:
        try:
            alt = kata_to_hira(str(feat[9] or ""))
        except Exception:
            alt = ""
        if alt and alt != reading_hira:
            pieces = split_pieces(surface, alt)
            if pieces is not None:
                reading_hira = alt
        if pieces is None:
            # 「行こう」的发音形是 いこー：把 ー 还原成 surface 上对应的假名再试
            m = re.search(r"[ういう]ー?$", surface)
            if alt and m:
                fixed = alt
                for i, ch in enumerate(surface):
                    if i < len(fixed) and fixed[i] == "ー":
                        fixed = fixed[:i] + ch + fixed[i + 1:]
                if fixed != alt:
                    pieces = split_pieces(surface, fixed)
                    if pieces is not None:
                        reading_hira = fixed
    if pieces is None:
        return [{"text": surface, "ruby": None, "level": "C",
                 "reason": why("alignment_failed", "送り仮名对齐失败")}]

    # 纯数字：引擎常把 33 读成 サンサン，数字的读法是封闭规则，自己算
    if all(ch in NUMERALS for ch in surface):
        num = counters.parse_number(surface)
        fixed = counters.numeral_reading(num) if num else None
        if fixed:
            pieces = split_pieces(surface, fixed) or [(surface, fixed)]

    key = surface
    # 数词 + つ（四つ=よっつ、二つ=ふたつ）
    if line and start >= 0 and surface in counters.NUM_TSITSU:
        nxt = line[start + len(surface): start + len(surface) + 1]
        if nxt == "つ":
            return [{"text": surface, "ruby": counters.NUM_TSITSU[surface], "level": "A",
                     "source": "counter", "basis": "助数詞表"}]
    # 一人 / 二人 / 四人
    if surface in counters.NUM_NIN:
        return [{"text": surface, "ruby": counters.NUM_NIN[surface], "level": "A",
                 "source": "counter", "basis": "助数詞表"}]

    verdict = _word_decision(surface, reading_hira, key, pos, getattr(w, "is_oov", None))

    # 整词弃权：所有汉字片段都不标，理由挂在每个片段上
    if verdict.get("abstain"):
        out: list[dict] = []
        for text, ruby in pieces:
            item = {"text": text, "ruby": None, "level": "K" if not ruby else "C"}
            if ruby:
                item["reason"] = verdict["abstain"]
                if CONFIG.keep_ruby:
                    item["would_be"] = ruby
            out.append(item)
        return out

    source = verdict.get("source", "dict")
    # 人工钉死：整词直接用词表的读音
    forced = GLOSSARY.get(key)
    if forced and surface == key:
        pieces = [(surface, forced)]

    level, basis = assign_level(source, key, reading_hira)
    out = []
    cands = candidates_for(key) if level == "B" else []
    # 候选按整词切开：赤ん坊 + あかんぼう → ["あか","ぼう"]，前端才能逐片替换
    # 把我们实际标的那个读音排第一（用户悬停时先看到"系统选了哪个"）
    if len(cands) >= 2 and reading_hira in cands:
        cands = [reading_hira] + [c for c in cands if c != reading_hira]
    cand_parts = []
    if len(cands) >= 2:
        n_ruby = sum(1 for _, r in pieces if r)
        for c in cands:
            parts = split_pieces(surface, c)
            if not parts:
                continue
            rs = [x[1] for x in parts if x[1]]
            if len(rs) == n_ruby:
                cand_parts.append({"r": c, "p": rs})
    for text, ruby in pieces:
        if not ruby:
            out.append({"text": text, "ruby": None, "level": "K", "pos": pos})
        else:
            item = {"text": text, "ruby": ruby, "level": level,
                    "source": source, "basis": basis, "pos": pos}
            if len(cands) >= 2:
                item["cands"] = cands              # 悬停展示用
                item["wordbase"] = surface         # 整词（面板按它聚合）
                item["cand_parts"] = cand_parts
            out.append(item)
    return out


def apply_llm(line: str, segs: list[dict]) -> list[dict]:
    """B 档如果缓存里有 LLM 的选择，就用它换掉读音（只从候选里选，不生成）。

    实测：B 档 73.2% → 80.7%（净 +55 / 753）。A 档不许碰，C 档没有候选。
    """
    if not (CONFIG.llm and CONFIG.llm_choices):
        return segs
    for seg in segs:
        base = seg["base"]
        if seg.get("level") != "B":
            continue
        if not KANJI.search(base):
            continue
        cands = candidates_for(base)
        if len(cands) < 2:
            continue
        entry = CONFIG.llm_choices.get(cache_key(line, seg["start"], base, cands))
        if isinstance(entry, str):
            entry = {"r": entry, "c": 1.0}
        if not entry or entry.get("c", 0) < CONFIG.min_conf:
            continue
        chosen = entry.get("r")
        if chosen and chosen in cands:
            seg["ruby"] = chosen
            seg["source"] = "llm"                 # 档位仍是 B：LLM 在 B 上是 80.7%
            seg["basis"] = f'LLM 选 {chosen}（conf {entry.get("c", 0):.2f}）'
    return segs




_PHRASE_BY_FIRST: dict[str, list[str]] = {}


VOICED = {"か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
          "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
          "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
          "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ"}
SOKUON = set("つちくき")


def annotate_line(line: str, options: dict) -> dict:
    if not line:
        return {"text": line, "segments": []}
    tagger = get_tagger()
    if tagger is None:
        return {"text": line, "segments": [{
            "base": line, "ruby": None, "level": "C" if KANJI.search(line) else "K",
            "start": 0, "end": len(line), "reason": "m0: 未接入分词器",
        }]}

    segs: list[dict] = []
    pos = 0
    for widx, w in enumerate(tagger(line)):
        tok_start = line.find(w.surface, pos)
        for piece in annotate_token(w, line, tok_start):
            t = piece.pop("text")
            start = line.find(t, pos)
            if start < 0:                      # 分词与原文不一致 → 整行放弃
                return {"text": line, "segments": [{
                    "base": line, "ruby": None, "level": "C", "start": 0, "end": len(line),
                    "reason": "token 与原文不一致",
                }]}
            segs.append({"base": t, "start": start, "end": start + len(t), "word": widx, **piece})
            pos = start + len(t)
    if "counters" not in CONFIG.disable:
        segs = counters.merge_counters(line, segs)
    segs = apply_llm(line, segs)
    # 政策层：只决定"要不要输出"，不决定读音
    if CONFIG.emit != "B":
        limit = LEVEL_RANK.get(CONFIG.emit, 2)
        for seg in segs:
            if seg.get("ruby") and LEVEL_RANK.get(seg["level"], 3) > limit:
                seg["ruby"] = None
                seg["suppressed"] = True
    # 校验器：违反不变量的片段一律降为弃权，不做修补
    for bad in check_invariants(line, segs):
        seg = bad["seg"]
        seg["ruby"] = None
        seg["level"] = "C"
        seg["reason"] = why("invariant_failed", f'不变量 {bad["code"]} 未通过', detail=bad["detail"])
    return {"text": line, "segments": segs}


KANA_RE = re.compile(r"^[\u3041-\u3096\u30a1-\u30fa\u30fc]+$")


OPEN_PUNCT = set("「『（(［[【〈《“‘")
CLOSE_PUNCT = set("」』）)］]】〉》”’")
SENTENCE_END = set("。！？!?．.")


def _is_kana(x: str) -> bool:
    return bool(x) and bool(KANA_RE.match(x))


def add_reading_layers(line: str, segs: list[dict]) -> tuple[list[dict], str, str]:
    """给片段补 romaji / keys，并按词拼成整行。

    拼写规则：
      · 助詞（は/へ/を）按 POS 判：只有 POS 带「助詞」才读 wa/e/o
      · 助動詞贴前一个谓语（生きてる→ikiteru）；接终止形的不贴（でしょう）
      · 接頭辞（お/ご）与后面的词连写（お願って→onegatte）
      · 标点保留：开括号贴后词、闭括号与句末标点贴前词、句末标点后加空格
    """
    from .romaji import PARTICLES_WA, keys_pieces, morae, romaji_pieces, to_hira

    STANDALONE = {"でしょう", "だろう", "らしい", "よう", "ようだ", "みたい",
                  "そう", "そうだ", "かも"}

    # 1) 分组：同 word / 助動詞贴前 / 接頭辞贴后
    groups: list[list[dict]] = []
    for seg in segs:
        base = seg.get("base") or ""
        pos = seg.get("pos") or ""
        prev_parts = set((groups[-1][-1].get("pos") or "").split("/")) if groups else set()
        parts = set(pos.split("/"))
        is_predicate = bool(prev_parts & {"動詞", "形容詞"})
        prev_base = groups[-1][-1].get("base") or "" if groups else ""
        after_n = base in ("だ", "の") and prev_base.endswith("ん")
        is_aux = (("助動詞" in parts or base in ("て", "で")
                   or (base == "ん" and is_predicate))
                  and (is_predicate or after_n) and base not in STANDALONE)
        # お/ご 常被标成感動詞；后面接汉字时按接頭辞处理（お願い・ご無沙汰）
        prev_is_prefix = "接頭辞" in prev_parts or (
            bool(groups) and (groups[-1][-1].get("base") or "") in ("お", "ご")
            and base and "一" <= base[0] <= "鿿")
        if groups and (groups[-1][0].get("word") == seg.get("word") or is_aux or prev_is_prefix):
            groups[-1].append(seg)
        else:
            groups.append([seg])

    # 2) 以 っ 结尾的组并进下一组（叠辅音要看下一个假名）
    def _kana_of(g: list[dict]) -> str:
        return "".join(x.get("ruby") or (x["base"] if x["level"] == "K" else "") for x in g)

    merged: list[list[dict]] = []
    for group in groups:
        if merged and _kana_of(merged[-1]).endswith("っ"):
            merged[-1].extend(group)          # 前一组以 っ 结尾 → 并进来
            continue
        if _kana_of(group).startswith("っ") and merged:
            merged[-1].extend(group)          # 本组以 っ 开头 → 并进前一组
            continue
        merged.append(list(group))
    groups = merged

    # 3) 逐组转换
    pieces: list[tuple[str, str, str]] = []      # (kind, romaji, keys)；kind ∈ word/punct
    for group in groups:
        kana_word = ""
        for seg in group:
            kana = seg.get("ruby") or (seg["base"] if seg["level"] == "K" else "")
            kana = kana if _is_kana(kana) else ""
            seg.setdefault("_kana", kana)
            kana_word += kana

        is_punct = not kana_word and len(group) == 1 and not (group[0].get("ruby"))
        if is_punct:
            text = group[0]["base"]
            group[0]["romaji"] = text
            group[0]["keys"] = text
            pieces.append(("punct", text, text))
            group[0].pop("_kana", None)
            continue

        r_units = romaji_pieces(kana_word) if kana_word else []
        k_units = keys_pieces(kana_word) if kana_word else []
        pos_u = 0
        for seg in group:
            n = len(morae(to_hira(seg.get("_kana", "")))) if seg.get("_kana") else 0
            seg["romaji"] = "".join(r_units[pos_u:pos_u + n]) if n else None
            seg["keys"] = "".join(k_units[pos_u:pos_u + n]) if n else None
            pos_u += n
            seg.pop("_kana", None)
        for seg in group:
            raw = seg.get("base") if seg["level"] == "K" else None
            if raw in PARTICLES_WA and "助詞" in set((seg.get("pos") or "").split("/")):
                seg["romaji"] = PARTICLES_WA[raw]
        pieces.append(("word",
                       "".join(seg.get("romaji") or "" for seg in group),
                       "".join(seg.get("keys") or "" for seg in group)))

    # 4) 拼行：开括号贴后、闭括号/句末贴前，词间空格
    def assemble(idx: int) -> str:
        out = ""
        pending_open = ""
        for kind, r, k in pieces:
            tok = r if idx == 1 else k
            if not tok:
                continue
            if kind == "punct":
                if tok in OPEN_PUNCT:
                    if out and not out.endswith(" ") and not pending_open:
                        out += " "
                    pending_open += tok
                elif tok in SENTENCE_END:
                    out += tok + " "
                else:
                    out += tok
                continue
            if pending_open:
                out += pending_open + tok
                pending_open = ""
            elif out and not out.endswith(" "):
                out += " " + tok
            else:
                out += tok
        return (pending_open + out).strip()

    return segs, assemble(1), assemble(2)


def annotate(req: dict) -> dict:
    text = str(req.get("text") or "")
    options = req.get("options") or {}
    layers = req.get("layers") or ["ruby"]

    lines = [annotate_line(ln, options) for ln in text.split("\n")]
    romaji_lines: list[str] = []
    keys_lines: list[str] = []
    if "romaji" in layers or "keys" in layers:
        for item in lines:
            _, rl, kl = add_reading_layers(item["text"], item["segments"])
            romaji_lines.append(rl)
            keys_lines.append(kl)

    out = {"version": VERSION, "lines": lines}
    if "romaji" in layers:
        out["romaji"] = {"lines": romaji_lines, "text": "\n".join(romaji_lines)}
    if "keys" in layers:
        out["keys"] = {"lines": keys_lines, "text": "\n".join(keys_lines)}

    total = sum(len(x["segments"]) for x in lines)
    annotated = sum(1 for x in lines for s in x["segments"] if s.get("ruby"))
    out["stats"] = {
        "segments": total,
        "annotated": annotated,
        "coverage": round(annotated / total, 4) if total else 0.0,
    }
    return out


def serve_stdio() -> None:
    load_tables()
    get_tagger()                                  # 先预热，避免第一行超时
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"bad json: {e}"}, ensure_ascii=False), flush=True)
            continue
        try:
            resp = annotate(req)
        except Exception as e:
            resp = {"error": f"{type(e).__name__}: {e}", "version": VERSION, "lines": []}
        print(json.dumps(resp, ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--text")
    ap.add_argument("--llm", action="store_true", help="用 LLM 缓存里的选择覆盖多候选词")
    ap.add_argument("--llm-min-conf", type=float, default=0.0)
    ap.add_argument("--keep-ruby", action="store_true", help="弃权的片段也带上 would_be 读音（统计用）")
    ap.add_argument("--check-tables", action="store_true", help="打印各表条目数后退出")
    ap.add_argument("--layers", default="ruby",
                    help="要生成哪些层，逗号分隔：ruby,romaji,keys")
    ap.add_argument("--oov-mode", choices=["abstain", "mark"], default="abstain",
                    help="OOV 处理：abstain 弃权（默认）/ mark 标成 B")
    ap.add_argument("--disable", default="", help="诊断用：逗号分隔关掉 glossary/heteronym/counters")
    ap.add_argument("--emit", choices=["A", "AB", "B"], default="B",
                    help="政策层：只输出到这一档（A 最保守，B 全出）")
    a = ap.parse_args()
    CONFIG.llm = a.llm
    CONFIG.min_conf = a.llm_min_conf
    CONFIG.keep_ruby = a.keep_ruby
    CONFIG.emit = a.emit
    CONFIG.oov_mode = a.oov_mode
    CONFIG.disable = {x for x in a.disable.split(",") if x}
    load_tables()
    if a.check_tables:
        print(json.dumps({
            "heteronym": len(TABLES.heteronym),
            "candidates": len(TABLES.candidates),
            "stats": len(TABLES.stats),
            "glossary": len(GLOSSARY),
        }, ensure_ascii=False, indent=2))
        return
    if a.text is not None:
        layers = [x for x in a.layers.split(",") if x]
        print(json.dumps(annotate({"text": a.text, "layers": layers}),
                         ensure_ascii=False, indent=2))
        return
    if a.stdio:
        serve_stdio()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
