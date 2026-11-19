#!/usr/bin/env python3
"""运行参数（B 类阈值）的读取。

查找顺序：data/config.json（本机覆盖）→ config/defaults.json（仓库默认）
A 类设计常量不放这里 —— 它们在 thresholds.py，改完必须重跑评测。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "config" / "defaults.json"
LOCAL = ROOT / "data" / "config.json"

_FALLBACK = {
    "lyrics": {"mb_max_delta": 3.0, "fallback_max_delta": 30.0, "min_content_lines": 3,
               "name_min_len": 4, "kana_ratio_min": 0.10, "lang_min_chars": 20,
               "weights": {"title": 40, "artist": 20, "duration": 40},
               "delta_tiers": [3, 10, 30]},
    "player": {"coverage_warn": 0.7, "merge_same_ts": 0.05,
               "speed_min": 0.5, "speed_max": 1.25, "music_dirs": [],
               "ui": {"wave_span": 5, "wave_span_min": 2, "wave_span_max": 10,
                      "wave_height": 120, "autosave_ms": 1500, "undo_steps": 50,
                      "toast_ms": 4200, "follow_default": True}},
    "waveform": {"rate": 8000, "step": 0.02},
    "vocals": {"model": "htdemucs", "auto_start": True,
               "hf_endpoint": "https://hf-mirror.com", "sample_rate": 16000,
               "frame_sec": 0.02, "ratio_min": 0.05, "abs_threshold": 200,
               "floor_mult": 3},
    "library": {"extensions": [".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg"],
                "auto_pair_lrc": True},
    "app": {"window_width": 1280, "window_height": 820, "window_min": [960, 600],
            "log_max_bytes": 2097152},
}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


CFG = _merge(_merge(_FALLBACK, _load(DEFAULTS)), _load(LOCAL))

LY = CFG["lyrics"]           # 歌词匹配
PL = CFG["player"]           # 播放器通用
PUI = PL["ui"]               # 前端界面行为
WV = CFG["waveform"]         # 波形峰值
VC = CFG["vocals"]           # 人声分离
LB = CFG["library"]          # 曲库扫描/导入
APP = CFG["app"]             # 桌面壳/日志


def show() -> str:
    return json.dumps(CFG, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(show())
