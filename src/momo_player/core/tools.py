"""外部工具解析：优先显式路径，其次包内，再其次常见安装目录。"""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

from momo_yomi.paths import BUNDLE


def _candidates(name: str) -> list[Path]:
    out = []
    b = BUNDLE / "bin"
    if b.is_dir():
        out.append(b / name)
    machine = Path("/opt/homebrew/bin") / name
    intel = Path("/usr/local/bin") / name
    out += [machine, intel, Path.home() / ".local" / "bin" / name,
            Path.home() / ".pyenv" / "shims" / name]
    found = shutil.which(name)
    if found:
        out.append(Path(found))
    return out


def find_tool(name: str, env: str | None = None) -> str | None:
    """返回可执行工具路径；env 指定的路径优先。"""
    if env:
        value = os.environ.get(env)
        if value:
            p = Path(value)
            try:
                if p.is_file() and os.access(p, os.X_OK):
                    return str(p)
            except OSError:
                pass
    for p in _candidates(name):
        try:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
        except OSError:
            pass
    return None


def demucs_available() -> bool:
    """full 包里 demucs 是 Python 模块，thin 里可能是外部命令。"""
    if find_tool("demucs", "MOMO_DEMUCS"):
        return True
    try:
        return importlib.util.find_spec("demucs") is not None
    except (ImportError, ValueError):
        return False


def missing_tools() -> list[str]:
    missing = []
    if not find_tool("ffmpeg", "MOMO_FFMPEG"):
        missing.append("ffmpeg")
    if not demucs_available():
        missing.append("demucs")
    return missing
