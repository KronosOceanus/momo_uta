#!/usr/bin/env python3
"""LRC 读写业务：加载 / 保存 / 备份 / 恢复 / 导入文本。只依赖 core。"""
from __future__ import annotations

import json

from ..core import library as LIB
from ..core import lrc_doc as DOC
from ..core import lrc_files as LRC
from .song import load_lyrics, save_lyrics


def _tokens_for(seg, ids, text):
    """把 seg + tid 转成带字符 span 的编辑器 token。"""
    if not seg or not isinstance(ids, list) or len(ids) != len(seg):
        return []
    pos = 0
    out = []
    for i, part in enumerate(seg):
        base = str(part[0] or "") if part else ""
        if not base:
            return []
        end = pos + len(base)
        if text[pos:end] != base:
            return []
        out.append({"tid": ids[i], "start": pos, "end": end,
                    "base": base, "ruby": part[1] if len(part) > 1 else None,
                    "level": part[2] if len(part) > 2 else None})
        pos = end
    return out if pos == len(text) else []


def lrc_action(req):
    act = req.get("action") or "load"
    item = LIB.resolve(req.get("uid"))
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    uid, title, artist = item.get("uid"), item["title"], item.get("artist", "")
    if act == "load":
        doc, has_lines = load_lyrics(item)
        trans = doc.get("translations") or {}
        ann = doc.get("annotations") or {}
        lids = doc.get("line_ids") or {}
        tids = doc.get("token_ids") or {}
        lines = []
        for i, ln in enumerate(doc.get("lines") or []):
            row = {**ln, "trans": trans.get(i, "")}
            if lids.get(i):
                row["lid"] = lids[i]
            tokens = _tokens_for(ann.get(i), tids.get(i), ln.get("text") or "")
            if tokens:
                row["tokens"] = tokens
            lines.append(row)
        return {**doc, "lines": lines,
                "pending": not has_lines and not doc.get("disabled")}
    if act == "backup":
        return LRC.backup_status(item["file"], uid, title, artist)
    if act == "restore":
        res = LRC.restore_backup(item["file"], uid, title, artist,
                                 expected_version=req.get("version"))
        if res.get("ok"):
            try:
                LIB.refresh(item.get("uid"))
                res["refresh_ok"] = True
            except Exception as e:
                res["refresh_ok"] = False
                res["refresh_error"] = str(e)
        return res
    if act == "delete":
        res = LRC.delete_store(item["file"], uid, title, artist,
                               expected_version=req.get("version"))
        if res.get("ok"):
            try:
                LIB.refresh(item.get("uid"))
                res["refresh_ok"] = True
            except Exception as e:
                res["refresh_ok"] = False
                res["refresh_error"] = str(e)
        return res
    if act == "export":
        lines = req.get("lines")
        doc = LRC.load(item["file"], uid, title, artist)
        if not lines:
            lines = doc["lines"]
        ann = doc.get("annotations") or {}
        trans = doc.get("translations") or {}
        if lines and any("trans" in x for x in lines):
            trans = {i: x.get("trans") or "" for i, x in enumerate(lines)
                     if (x.get("trans") or "").strip()}
        elif req.get("translations"):
            trans = {int(k): str(v) for k, v in req["translations"].items() if str(v or "").strip()}
        same_lines = [ln.get("text") for ln in lines] == [ln.get("text") for ln in doc["lines"]]
        lids = doc.get("line_ids") if same_lines else None
        tids = doc.get("token_ids") if same_lines else None
        return {"ok": True, "nhlrc": DOC.render_nhlrc(lines, doc["metadata"], ann, trans,
                                                       line_ids=lids, token_ids=tids),
                "lrc": DOC.render_body(lines, doc["metadata"])}
    if act == "import_lrc":
        text = str(req.get("text") or "")
        if not text.strip():
            return {"ok": False, "error": "文件是空的"}
        return save_lyrics(item, mode="replace", text=text,
                           expected_version=req.get("version"))
    if act == "save":
        lines = req.get("lines") or []
        if not lines or not any((ln.get("text") or "").strip() for ln in lines):
            return {"ok": False, "error": "没有歌词行"}
        trans = req.get("translations")
        if trans is None:
            trans = {i: ln.get("trans") or "" for i, ln in enumerate(lines)
                     if "trans" in ln}
        return save_lyrics(item, lines, "align", expected_version=req.get("version"),
                           translations=trans)
    return {"ok": False, "error": "未知动作"}

