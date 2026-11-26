"""假名工具。原先在 5 个文件里各有一份，统一到这里。"""
from __future__ import annotations


def kata_to_hira(s: str) -> str:
    """片假名 → 平假名。长音符「ー」保留，汉字/拉丁原样不动。"""
    def conv(c: str) -> str:
        if c in ("ヶ", "ヵ"):
            return "か"
        return chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c
    return "".join(conv(c) for c in s)
