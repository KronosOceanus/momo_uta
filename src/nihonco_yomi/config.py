#!/usr/bin/env python3
"""运行参数（B 类阈值）的读取。

默认值只来自 config/defaults.json；data/config.json 做本机覆盖。
A 类设计常量不放这里 —— 它们在 thresholds.py，改完必须重跑评测。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "config" / "defaults.json"
LOCAL = ROOT / "data" / "config.json"

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


CFG = _merge(_load(DEFAULTS), _load(LOCAL))
if not CFG:
    raise RuntimeError(f"缺少默认配置：{DEFAULTS}")

LY = CFG["lyrics"]           # 歌词匹配
PL = CFG["player"]           # 播放器通用
PUI = PL["ui"]               # 前端界面行为
WV = CFG["waveform"]         # 波形峰值
VC = CFG["vocals"]           # 人声分离
LB = CFG["library"]          # 曲库扫描/导入
APP = CFG["app"]             # 桌面壳/日志
JOB = CFG["jobs"]            # 统一任务


def show() -> str:
    return json.dumps(CFG, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(show())
