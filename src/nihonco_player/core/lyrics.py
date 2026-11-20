#!/usr/bin/env python3
"""歌词模块的对外门面。

实现按职责分三层：
  lyrics_text.py    解析 / 名字匹配 / 语言判定（纯函数）
  lyrics_cache.py   键、路径、命中、写入
  lyrics_fetch.py   网易云 / MB / lrclib + 挑选与编排

外部（server / importing / library / tests）继续 from . import lyrics as LY。
"""
from __future__ import annotations

from nihonco_yomi.config import LY as CFG  # noqa: F401

from .lyrics_cache import _cached, cache_path, set_cache_dir, write_local_lrc  # noqa: F401
from .lyrics_fetch import (audio_duration, auto_match, accept_candidate, best_by_duration,  # noqa: F401
                           fetch_candidate, fetch_lrc_by_id, get_lrc, lrclib,
                           mb_canonical, netease, scan, score_candidate,
                           search_candidates, valid_lrc)
from .lyrics_text import (JP, KANA_RE, HAN_RE, LAT_RE, LRC,  # noqa: F401
                          clean_artist, content_lines, has_timed, is_excluded,
                          is_likely_song, kind, lang_guess, parse_lrc,
                          split_name)
from .lyrics_text import _match, _norm  # noqa: F401
from .lyrics_cache import _key  # noqa: F401
