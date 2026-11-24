#!/usr/bin/env python3
"""运行参数（B 类阈值）的读取。

默认值只来自 config/defaults.json；data/config.json 做本机覆盖。
A 类设计常量不放这里 —— 它们在 thresholds.py，改完必须重跑评测。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from .paths import CONFIG, ROOT

DEFAULTS = CONFIG / "defaults.json"
LOCAL = ROOT / "data" / "config.json"
LOCAL_CONFIG_WARNING = ""


class ConfigFileError(RuntimeError):
    """用户配置损坏且无法安全备份，调用方不得继续写入。"""


def _backup_bad(path: Path) -> str:
    """把损坏文件移到唯一备份名；失败返回空串。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = path.with_name(f"{path.name}.bad-{stamp}")
    out = base
    n = 1
    while out.exists():
        n += 1
        out = base.with_name(f"{base.name}-{n}")
    try:
        path.replace(out)
        return str(out)
    except OSError:
        # 跨卷/权限特殊情况下用复制，成功后删原文件。
        try:
            shutil.copy2(path, out)
            os.unlink(path)
            return str(out)
        except OSError:
            return ""


def read_local_config(path: str | Path | None = None, *, strict: bool = False) -> dict:
    """读 data/config.json；损坏时备份并回退，绝不让调用方覆盖原文件。"""
    global LOCAL_CONFIG_WARNING
    p = Path(path) if path is not None else LOCAL
    if not p.is_file():
        return {}
    try:
        raw = p.read_text(encoding="utf-8")
    except Exception as e:
        LOCAL_CONFIG_WARNING = f"配置文件无法读取：{e}"
        if strict:
            raise ConfigFileError(LOCAL_CONFIG_WARNING) from e
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("顶层必须是对象")
        _validate_local(data)
    except Exception as e:
        bad = _backup_bad(p)
        if bad:
            LOCAL_CONFIG_WARNING = f"配置文件损坏，已备份为 {bad}，当前使用默认配置"
        else:
            LOCAL_CONFIG_WARNING = f"配置文件损坏且无法备份：{e}"
        if strict and not bad:
            raise ConfigFileError(LOCAL_CONFIG_WARNING) from e
        return {}
    LOCAL_CONFIG_WARNING = ""
    return data


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


_MIN_VALUES = {
    "http.timeout_s": 1,
    "http.max_body_bytes": 1024,
    "jobs.max_active": 1,
    "jobs.max_active_match": 1,
    "jobs.poll_ms": 10,
    "jobs.vocals_poll_ms": 10,
    "jobs.keep_done": 0,
    "vocals.max_bytes": 1,
    "vocals.queue_timeout_s": 1,
    "vocals.run_timeout_s": 1,
    "waveform.timeout_s": 1,
    "waveform.concurrent": 1,
    "library.max_import_paths": 1,
    "library.max_scan_files": 1,
    "lyrics.max_name_bytes": 1,
    "app.log_max_bytes": 1024,
    "app.log_keep_files": 1,
    "app.window_width": 1,
    "app.window_height": 1,
}


def _validate_value(path: str, value, default) -> None:
    """只校验已知键的结构；未知键保留，避免把用户扩展当成损坏。"""
    if path in _MIN_VALUES and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < _MIN_VALUES[path]:
            raise ValueError(f"{path} 不能小于 {_MIN_VALUES[path]}")
    if path in ("lyrics.delta_tiers",) and (
            not isinstance(value, list) or len(value) != 3):
        raise ValueError(f"{path} 必须是 3 个元素的数组")
    if path == "app.window_min" and (
            not isinstance(value, list) or len(value) != 2):
        raise ValueError(f"{path} 必须是 2 个元素的数组")
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{path} 必须是对象")
        for k, dv in default.items():
            if k in value:
                _validate_value(f"{path}.{k}", value[k], dv)
        return
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{path} 必须是数组")
        if default:
            for item in value:
                _validate_value(f"{path}[]", item, default[0])
        return
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{path} 必须是布尔值")
        return
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} 必须是整数")
        return
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} 必须是数字")
        return
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"{path} 必须是字符串")


def _validate_local(data: dict) -> None:
    for key, dv in _load(DEFAULTS).items():
        if key in data:
            _validate_value(key, data[key], dv)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_LOCAL_CFG = read_local_config()
CFG = _merge(_load(DEFAULTS), _LOCAL_CFG)
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
