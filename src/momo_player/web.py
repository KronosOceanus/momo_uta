#!/usr/bin/env python3
"""页面装配：HTML/CSS/JS 都在 static/ 下，这里只负责注入配置。"""
from __future__ import annotations

from pathlib import Path

import json

from momo_yomi.config import CFG, PUI

STATIC = Path(__file__).parent / "static"


def page(token: str = "", nonce: str = "") -> str:
    html = (STATIC / "player.html").read_text(encoding="utf-8")
    cfg = json.dumps(CFG, ensure_ascii=False).replace("</", "<\\/")
    theme = "light" if PUI.get("theme") == "light" else "dark"
    html = html.replace('<html lang="ja" data-theme="dark">',
                        f'<html lang="ja" data-theme="{theme}">', 1)
    tok = json.dumps(token).replace("</", "<\\/")
    n = f' nonce="{nonce}"' if nonce else ""
    inject = (f'<script{n}>window.__CFG = {cfg};'
              f'window.__MOMO_TOKEN = {tok};</script>\n')
    return html.replace("<head>", "<head>\n" + inject, 1)
