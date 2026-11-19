#!/usr/bin/env python3
"""LRC 读写业务：加载 / 保存 / 备份 / 恢复 / 导入文本。只依赖 core。"""
from __future__ import annotations

import json

from ..core import library as LIB
from ..core import lrcio as LRC
from ..core.library import CACHE
from .song import annotate_line_with_notes, segs_of

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
    if act == "export":
        lines = req.get("lines")
        doc = LRC.load(item["file"])
        if not lines:
            lines = doc["lines"]
        ann = doc.get("annotations") or {}
        return {"ok": True, "nhlrc": LRC.render_nhlrc(lines, doc["metadata"], ann),
                "lrc": LRC.render_body(lines, doc["metadata"])}
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
        doc = LRC.load(item["file"])
        old = doc.get("annotations") or {}
        ann = {}
        for i, ln in enumerate(lines):
            text = (ln.get("text") or "").strip()
            if not text:
                continue
            st = old.get(i)
            if st and "".join(x[0] for x in st) == text:
                ann[i] = st                     # 正文没动 → 沿用文件里的标注
            else:
                try:
                    ann[i] = segs_of(annotate_line_with_notes(text))
                except Exception:
                    pass
        res = LRC.save(item["file"], lines, ann)
        lib = LIB.scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})
        res["library"] = len(lib)
        return res
    return {"ok": False, "error": "未知动作"}

