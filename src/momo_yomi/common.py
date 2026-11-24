"""评测与工具用的公共设施（路径从 paths.py 来）。

引擎不 import 这个文件；只有 tools/ 用得到。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

from .paths import CACHE, CORPUS, CURATED, ROOT, TABLES

# 评测
EVAL = ROOT / "eval"
GOLD = EVAL / "gold"            # 标准答案（资产）
REPORTS = EVAL / "reports"      # 自动生成（可重建）

__all__ = [
    "CACHE", "CORPUS", "CURATED", "ROOT", "TABLES",
    "EVAL", "GOLD", "REPORTS",
    "DEFAULT_CMD", "Annotator",
    "segments_of", "run_all", "load_gold", "normalize",
]

DEFAULT_CMD = [sys.executable, "-m", "momo_yomi.annotate", "--stdio"]


class Annotator:
    """常驻的 stdio 标注器。"""

    def __init__(self, cmd: list[str] | str | None = None, timeout: int = 60):
        if cmd is None:
            argv = DEFAULT_CMD
        elif isinstance(cmd, str):
            argv = cmd.split()
        else:
            argv = cmd
        self.timeout = timeout
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )

    def annotate(self, text: str) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("标注器没有响应（进程退出了？）")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)

    def __enter__(self) -> "Annotator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def segments_of(resp: dict) -> list[dict]:
    """把一次响应的所有 segment 摊平。"""
    return [s for line in resp.get("lines") or [] for s in line.get("segments") or []]


def run_all(lines: list[str], extra_args: list[str] | None = None) -> list[dict]:
    """批量标注，返回与输入同序的响应列表。"""
    out = []
    with Annotator(DEFAULT_CMD + (extra_args or [])) as ann:
        for ln in lines:
            out.append(ann.annotate(ln))
    return out


def load_gold(files: list[Path]) -> list[dict]:
    """读若干 jsonl，返回记录列表。"""
    out = []
    for f in files:
        if f.exists():
            out += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def normalize(s: str) -> str:
    """比较用：NFKC + 片假名→平假名。"""
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(
        chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s
    )
