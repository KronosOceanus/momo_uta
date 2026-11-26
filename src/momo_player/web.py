#!/usr/bin/env python3
"""页面装配：HTML/CSS/JS 都在 static/ 下，这里只负责注入配置。"""
from __future__ import annotations

from pathlib import Path

import json

from momo_yomi.config import CFG, LOCAL_CONFIG_WARNING, PUI
from .core import tools as TOOLS

STATIC = Path(__file__).parent / "static"


def page(token: str = "", nonce: str = "") -> str:
    html = (STATIC / "player.html").read_text(encoding="utf-8")
    cfg = json.dumps(CFG, ensure_ascii=False).replace("</", "<\\/")
    theme = "light" if PUI.get("theme") == "light" else "dark"
    html = html.replace('<html lang="ja" data-theme="dark">',
                        f'<html lang="ja" data-theme="{theme}">', 1)
    tok = json.dumps(token).replace("</", "<\\/")
    n = f' nonce="{nonce}"' if nonce else ""
    warning = json.dumps(LOCAL_CONFIG_WARNING).replace("</", "<\\/")
    missing = TOOLS.missing_tools()
    tool_warning = ""
    if missing:
        tool_warning = "缺少外部工具：" + " / ".join(missing) + "。可安装或设置 MOMO_FFMPEG / MOMO_DEMUCS"
    tool_warning = json.dumps(tool_warning).replace("</", "<\\/")
    inject = (f'<script{n}>window.__CFG = {cfg};'
              f'window.__MOMO_TOKEN = {tok};'
              f'window.__MOMO_CONFIG_WARNING = {warning};'
              f'window.__MOMO_TOOL_WARNING = {tool_warning};</script>\n')
    return html.replace("<head>", "<head>\n" + inject, 1)
