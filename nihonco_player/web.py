#!/usr/bin/env python3
"""页面装配：HTML/CSS/JS 都在 static/ 下，这里只负责注入配置。"""
from __future__ import annotations

from pathlib import Path

from nihonco_yomi.config import PL as PCFG

STATIC = Path(__file__).parent / "static"


def page() -> str:
    html = (STATIC / "player.html").read_text(encoding="utf-8")
    return (html.replace("__SMIN__", f'{PCFG["speed_min"]}')
                .replace("__SMAX__", f'{PCFG["speed_max"]}')
                .replace("__SSTEP__", "0.05"))


PAGE = page()
