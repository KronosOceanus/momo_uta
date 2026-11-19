#!/usr/bin/env python3
"""从 JMdict + KANJIDIC2 抽词典表（命名规则：来源_表名.json）。

    data/tables/jmdict_readings.json             全量 词形 → 读音
    data/tables/jmdict_common_readings.json      常用读音（LLM 候选）
    data/tables/jmdict_heteronym.json            多音词（≥2 个读音）
    三张表：heteronym（多音词）· readings（全量读音）· common（常用读音，LLM 候选）。

抽取原则：
    · 读音不按「汉字的常规音训拼出来」→ 视为熟字訓/当て字
    · 同一个汉字形对应多个读音 → 多音词
    · 判定偏「严」：宁可多收进熟字訓表，也不漏（多收的后果只是按词典读音标，不会错）

用法:
    python3 tools/build_tables.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from nihonco_yomi.kana import kata_to_hira

from tools.common import SOURCES, TABLES as OUT
CACHE = SOURCES / "jmdict"

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")
HAN = re.compile(r"[\u4e00-\u9fff\u3005\u3006]+")
KANA = re.compile(r"[ぁ-ん]+")

VOICED = {"か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
          "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
          "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
          "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ"}
UNVOICED = {v: k for k, v in VOICED.items()}
SOKUON = {"く", "つ", "ち", "き"}



def stems(reading: str) -> list[str]:
    """把 おお.きい 变成 おお；おと.す 变成 おと"""
    r = reading.replace(".", "")
    out = {r}
    if "." in reading:
        out.add(reading.split(".")[0])
    return list(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jm = json.loads(next(CACHE.glob("jmdict-eng-*.json")).read_text(encoding="utf-8"))
    print(f"JMdict {len(jm['words'])} 条")

    pair_readings: dict[str, set[str]] = defaultdict(set)
    order: dict[str, list[str]] = defaultdict(list)      # JMdict 里的出现顺序
    common_set: dict[str, set[str]] = defaultdict(set)
    common_pairs: set[tuple[str, str]] = set()
    irregular: set[tuple[str, str]] = set()
    common: dict[str, bool] = {}
    nf: dict[str, int] = {}

    for w in jm["words"]:
        kanji_forms = [k["text"] for k in (w.get("kanji") or []) if k.get("text")]
        kana = [k for k in (w.get("kana") or []) if k.get("text")]
        if not kanji_forms or not kana:
            continue
        for kf in kanji_forms:
            if not KANJI.search(kf):
                continue
            for k in kana:
                tags = set(k.get("tags") or [])
                if "ok" in tags or "ik" in tags:      # 非常用/非常读，跳过
                    continue
                is_common = bool(k.get("common")) or any(x.get("common") for x in (w.get("kanji") or []))
                r = kata_to_hira(k["text"])
                if not KANA.fullmatch(r.replace("ー", "")):
                    continue
                pair_readings[kf].add(r)
                if r not in order[kf]:
                    order[kf].append(r)
                if is_common:
                    common_pairs.add((kf, r))
                    common_set[kf].add(r)
                if tags & {"gikun", "ateji"}:
                    irregular.add((kf, r))
                if k.get("common") or any(x.get("common") for x in (w.get("kanji") or [])):
                    common[kf] = True
                for s in w.get("sense", []):
                    for t in s.get("tags", []) or []:
                        m = re.fullmatch(r"nf(\d\d)", t)
                        if m:
                            nf[kf] = min(nf.get(kf, 99), int(m.group(1)))

    # 熟字訓严格：只用「常用」的 (形,读) 对，避免 大人=うし 这类生僻异读干扰
    by_form: dict[str, set[str]] = defaultdict(set)
    for form, r in common_pairs:
        by_form[form].add(r)
    # 多音词放宽一档：全部读音 ≥2 且至少一个常用 → 收录（含 きわ/ぎわ/さい 这种）

    heteronym: dict[str, list[str]] = {}
    for form, rs in by_form.items():
        rs = sorted(rs)
        if len(rs) >= 2:
            heteronym[form] = rs

    # 多音词放宽一档：全部读音 ≥2 且至少一个常用 → 也收（把 際 きわ/ぎわ/さい 收进来）
    for form, rs in pair_readings.items():
        if len(rs) >= 2 and form in common_set:
            heteronym[form] = sorted(rs)

    (OUT / "jmdict_heteronym.json").write_text(
        json.dumps(heteronym, ensure_ascii=False), encoding="utf-8")
    # 候选读音表：所有有 ≥2 个读音的词（不做 common 过滤），只用于"列候选"
    cands = {k: sorted(v) for k, v in pair_readings.items() if len(v) >= 2}
    (OUT / "jmdict_candidates.json").write_text(
        json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    print(f"候选读音词   {len(cands)} 个")

    # 常用读音（每个词形只留 common 的那些），给 LLM 当候选，避免生僻读音干扰
    (OUT / "jmdict_common_readings.json").write_text(
        json.dumps({k: sorted(v) for k, v in common_set.items()}, ensure_ascii=False), encoding="utf-8")
    # 全量 形→读音，供「UniDic vs JMdict 冲突检测」用
    (OUT / "jmdict_readings.json").write_text(
        json.dumps({k: sorted(v) for k, v in pair_readings.items()}, ensure_ascii=False), encoding="utf-8")

    print(f"多音词       {len(heteronym)} 条")
    print(f"已知汉字形   {len(pair_readings)} 个")
    print(f"常用读音条目 {len(common_set)} 个词形")

if __name__ == "__main__":
    main()
