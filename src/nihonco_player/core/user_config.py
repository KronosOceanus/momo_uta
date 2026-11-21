#!/usr/bin/env python3
"""本机配置覆盖：只写 data/config.json，不碰 defaults。"""
from __future__ import annotations

from nihonco_yomi.paths import ROOT

from . import fsio as FS

FILE = ROOT / "data" / "config.json"
LOCK = FILE.with_suffix(".lock")


def set_theme(theme: str) -> str:
    theme = "light" if str(theme) == "light" else "dark"
    with FS.locked(LOCK):
        d = FS.read_json(FILE, {}) or {}
        player = d.setdefault("player", {})
        ui = player.setdefault("ui", {})
        ui["theme"] = theme
        FS.atomic_write_json(FILE, d, indent=1)
    return theme
