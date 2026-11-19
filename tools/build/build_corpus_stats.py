#!/usr/bin/env python3
"""从语料读音频次生成「多音字读音分布」表。

输入  data/corpus/ndl_aozora_freq.json      词形 → {读音: 次数}（NDL 青空文庫コーパス）
输出  data/corpus/ndl_reading_stats.json    词形 → {top, n, share}

收录两类词：
  1. JMdict 标注为多音字的词（heteronym 表）  —— 需要知道它们实际怎么读
  2. 语料里出现多个读音的汉字词（top 占比 <0.95）—— 词典没标多音，但实际是多音

用法：python3 tools/build_corpus_stats.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.common import CORPUS, TABLES  # noqa: E402

KANJI_ONLY = re.compile(r"^[\u4e00-\u9fff\u3005\u3006]+$")
from nihonco_yomi.thresholds import STATS_MULTI_SHARE as MULTI_SHARE   # noqa: E402
from nihonco_yomi.thresholds import STATS_MIN_TOTAL as MIN_TOTAL        # noqa: E402


def main() -> None:
    freq_path = CORPUS / "ndl_aozora_freq.json"
    if not freq_path.exists():
        raise SystemExit(f"缺语料：{freq_path}（先跑 NDL 语料解析）")
    freq = json.loads(freq_path.read_text(encoding="utf-8"))
    het = json.loads((TABLES / "jmdict_heteronym.json").read_text(encoding="utf-8"))

    out: dict[str, dict] = {}
    for word, dist in freq.items():
        total = sum(dist.values())
        if total < MIN_TOTAL:
            continue
        top_r, top_n = max(dist.items(), key=lambda kv: kv[1])
        share = top_n / total
        listed = word in het
        observed_multi = KANJI_ONLY.match(word) and len(word) <= 6 and share < MULTI_SHARE
        if not (listed or observed_multi):
            continue
        out[word] = {"top": top_r, "n": total, "share": round(share, 4),
                     "dist": dict(sorted(dist.items(), key=lambda kv: -kv[1])[:5])}

    dst = CORPUS / "ndl_reading_stats.json"
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    extra = sum(1 for w in out if w not in het)
    print(f"{dst.relative_to(dst.parents[2])} · {len(out)} 词（词典多音 {len(out) - extra} + 语料发现 {extra}）")


if __name__ == "__main__":
    main()
