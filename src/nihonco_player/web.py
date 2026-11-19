#!/usr/bin/env python3
"""页面装配：HTML/CSS/JS 都在 static/ 下，这里只负责注入配置。"""
from __future__ import annotations

from pathlib import Path

import json

from nihonco_yomi.config import CFG

STATIC = Path(__file__).parent / "static"


def page() -> str:
    html = (STATIC / "player.html").read_text(encoding="utf-8")
    cfg = json.dumps(CFG, ensure_ascii=False).replace("</", "<\\/")
    inject = f'<script>window.__CFG = {cfg};</script>\n'
    return html.replace("<head>", "<head>\n" + inject, 1)


PAGE = page()
