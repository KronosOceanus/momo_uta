#!/usr/bin/env python3
"""本机配置覆盖：只写 data/config.json，不碰 defaults。"""
from __future__ import annotations

from momo_yomi.paths import ROOT

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


PLAY_MODES = ("list", "one", "shuffle")


def set_play_mode(mode: str) -> str:
    mode = str(mode)
    if mode not in PLAY_MODES:
        raise ValueError("未知播放模式")
    with FS.locked(LOCK):
        d = FS.read_json(FILE, {}) or {}
        player = d.setdefault("player", {})
        ui = player.setdefault("ui", {})
        ui["play_mode"] = mode
        FS.atomic_write_json(FILE, d, indent=1)
    return mode
