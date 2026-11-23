#!/usr/bin/env python3
"""界面设置的持久化编排。"""
from __future__ import annotations

from momo_yomi.config import PUI

from ..core import user_config as UC


def set_theme(req: dict) -> dict:
    theme = str(req.get("theme") or "")
    if theme not in ("dark", "light"):
        return {"ok": False, "error": "未知主题"}
    try:
        theme = UC.set_theme(theme)
        PUI["theme"] = theme
    except Exception as e:
        return {"ok": False, "error": "保存主题失败：" + str(e)}
    return {"ok": True, "theme": theme}
