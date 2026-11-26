#!/usr/bin/env python3
"""页面装配：HTML/CSS/JS 都在 static/ 下，这里只负责注入配置。"""
from __future__ import annotations

from pathlib import Path

import json

from momo_yomi.config import CFG, LOCAL_CONFIG_WARNING, PUI
from .core import tools as TOOLS

STATIC = Path(__file__).parent / "static"


def _frontend_cfg() -> dict:
    """只给前端需要的配置，避免把 music_dirs 等绝对路径送到页面。"""
    player = CFG.get("player") or {}
    vocals = CFG.get("vocals") or {}
    return {
        "player": {
            "ui": dict(player.get("ui") or {}),
            "speed_min": player.get("speed_min"),
            "speed_max": player.get("speed_max"),
            "speed_step": player.get("speed_step"),
        },
        "jobs": dict(CFG.get("jobs") or {}),
        "vocals": {"auto_start": vocals.get("auto_start", True)},
    }


def page(nonce: str = "") -> str:
    html = (STATIC / "player.html").read_text(encoding="utf-8")
    cfg = json.dumps(_frontend_cfg(), ensure_ascii=False).replace("</", "<\\/")
    theme = "light" if PUI.get("theme") == "light" else "dark"
    html = html.replace('<html lang="ja" data-theme="dark">',
                        f'<html lang="ja" data-theme="{theme}">', 1)
    token_js = ("window.__MOMO_TOKEN = (()=>{try{return new URLSearchParams("
                "location.hash.slice(1)).get('token')||'';}catch(e){return '';}})();")
    n = f' nonce="{nonce}"' if nonce else ""
    warning = json.dumps(LOCAL_CONFIG_WARNING).replace("</", "<\\/")
    missing = TOOLS.missing_tools()
    tool_warning = ""
    if missing:
        tool_warning = "缺少外部工具：" + " / ".join(missing) + "。可安装或设置 MOMO_FFMPEG / MOMO_DEMUCS"
    tool_warning = json.dumps(tool_warning).replace("</", "<\\/")
    inject = (f'<script{n}>window.__CFG = {cfg};'
              f'{token_js}'
              f'window.__MOMO_CONFIG_WARNING = {warning};'
              f'window.__MOMO_TOOL_WARNING = {tool_warning};</script>\n')
    return html.replace("<head>", "<head>\n" + inject, 1)
