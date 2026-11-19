#!/usr/bin/env python3
"""LRC 读写业务：加载 / 保存 / 备份 / 恢复 / 导入文本。只依赖 core。"""
from __future__ import annotations

import json

from ..core import edits as ED
from ..core import library as LIB
from ..core import lrc_doc as DOC
from ..core import diag
from ..core import lrc_files as LRC
from ..core.library import CACHE
from .song import annotate_line_with_notes, fold_readings, segs_of

def lrc_action(req):
    item = CACHE.get(str(req.get("idx")))
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    act = req.get("action") or "load"
    uid, title, artist = item.get("uid"), item["title"], item.get("artist", "")
    if act == "load":
        return LRC.load(item["file"], uid, title, artist)
    if act == "backup":
        return LRC.backup_status(item["file"], uid, title, artist)
    if act == "restore":
        res = LRC.restore_backup(item["file"], uid, title, artist)
        if res.get("ok"):
            LIB.refresh(item.get("uid"))
        return res
    if act == "export":
        lines = req.get("lines")
        doc = LRC.load(item["file"], uid, title, artist)
        if not lines:
            lines = doc["lines"]
        ann = doc.get("annotations") or {}
        ann, _u, _d = fold_readings(item["key"], lines, ann)
        return {"ok": True, "nhlrc": DOC.render_nhlrc(lines, doc["metadata"], ann),
                "lrc": DOC.render_body(lines, doc["metadata"])}
    if act == "import_lrc":
        text = str(req.get("text") or "")
        if not text.strip():
            return {"ok": False, "error": "文件是空的"}
        res = LRC.import_text(item["file"], text, uid, title, artist)
        if LRC.exists(item["file"], uid) and item.get("key"):
            ED.pop(item["key"])            # 旧手改对应的是旧正文，覆盖后作废
        LIB.refresh(uid)
        return res
    if act == "save":
        lines = req.get("lines") or []
        if not lines or not any((ln.get("text") or "").strip() for ln in lines):
            return {"ok": False, "error": "没有歌词行"}
        doc = LRC.load(item["file"], uid, title, artist)
        old = DOC.align_annotations(lines, doc.get("annotations") or {})
        ann = {}
        for i, ln in enumerate(lines):
            text = (ln.get("text") or "").strip()
            if not text:
                continue
            st = old.get(i)
            if st and "".join(x[0] for x in st) == text:
                ann[i] = st                     # 正文没动 → 沿用对齐后的标注
            else:
                try:
                    ann[i] = segs_of(annotate_line_with_notes(text, stored=st))
                except Exception as e:
                    diag.log("annotate", f"保存时第 {i} 行注音失败：{e}")
        legacy = ED.for_song(item["key"])
        ann, used, dropped = fold_readings(item["key"], lines, ann)
        res = LRC.save(item["file"], lines, ann, uid, title, artist)
        if legacy:
            ED.pop(item["key"])
            diag.log("lyrics", f"{item['key']}: 保存时迁移手改 {used} 处，丢弃 {dropped} 处")
        res["library"] = LIB.refresh(uid)
        return res
    return {"ok": False, "error": "未知动作"}

