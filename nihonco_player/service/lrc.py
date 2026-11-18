#!/usr/bin/env python3
"""LRC 读写业务：加载 / 保存 / 备份 / 恢复 / 导入文本。只依赖 core。"""
from __future__ import annotations

import json

from ..core import library as LIB
from ..core import lrcio as LRC
from ..core.library import CACHE

def lrc_action(req):
    item = CACHE.get(str(req.get("idx")))
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    act = req.get("action") or "load"
    if act == "load":
        return LRC.load(item["file"])
    if act == "backup":
        return LRC.backup_status(item["file"])
    if act == "restore":
        res = LRC.restore_backup(item["file"])
        if res.get("ok"):
            lib = LIB.scan_library()
            CACHE.clear(); CACHE.update({str(i): x for i, x in enumerate(lib)})
        return res
    if act == "import_lrc":
        text = str(req.get("text") or "")
        if not text.strip():
            return {"ok": False, "error": "文件是空的"}
        res = LRC.import_text(item["file"], text)
        lib = LIB.scan_library()
        CACHE.clear(); CACHE.update({str(i): x for i, x in enumerate(lib)})
        return res
    if act == "save":
        lines = req.get("lines") or []
        if not lines:
            return {"ok": False, "error": "没有歌词行"}
        res = LRC.save(item["file"], lines)
        lib = LIB.scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})
        res["library"] = len(lib)
        return res
    return {"ok": False, "error": "未知动作"}

