#!/usr/bin/env python3
"""档位的全部阈值，集中在一处。

这些数字决定 A / AB / B 怎么切。改这里 = 改档位定义，
必须重跑 make stats + 三套歌词集（dev / test / gen）。
"""

# ── 判定链 ────────────────────────────────────────────────
MIN_CORPUS_N = 20          # 语料至少这么多次才拿来判档（再少是噪声）
SINGLE_READING_SHARE = 0.99  # 占比 ≥ 这个值 → 事实上只有一个读音 → A

# ── 语料统计表构建（build_corpus_stats）──────────────────
STATS_MIN_TOTAL = 20       # 总样本少于此值不进统计表
STATS_MULTI_SHARE = 0.95   # 主读占比低于此值 → 语料里确实多读，收进表
