#!/usr/bin/env python3
"""LRC 读写业务：加载 / 保存 / 备份 / 恢复 / 导入文本。只依赖 core。"""
from __future__ import annotations


from ..core import library as LIB
from ..core import lrc_files as LRC
from ..core.lrc_doc import tokens_with_spans
from . import lyric_document as LD
from .song import load_lyrics, save_lyrics


def lrc_action(req):
    act = req.get("action") or "load"
    item = LIB.resolve(req.get("uid"))
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    uid, title, artist = item.get("uid"), item["title"], item.get("artist", "")
    if act == "load":
        rows_doc = LD.load_rows(uid)
        rows_extra = None
        if rows_doc.get("ok") and rows_doc.get("model") == 2:
            rows_extra = rows_doc.get("rows") or []
            doc = LRC.doc_from_rows(rows_extra, rows_doc.get("version") or "",
                                    str(rows_doc.get("path") or ""))
            has_lines = bool(doc.get("lines"))
        else:
            doc, has_lines = load_lyrics(item)
        trans = doc.get("translations") or {}
        ann = doc.get("annotations") or {}
        lids = doc.get("line_ids") or {}
        tids = doc.get("token_ids") or {}
        compact = doc.get("lines") or []
        body_rows = doc.get("body_rows") or compact
        body_to_lyric = {}
        lyric = 0
        for bi, ln in enumerate(body_rows):
            if (ln.get("text") or "").strip():
                body_to_lyric[bi] = lyric
                lyric += 1
        lines = []
        for bi, ln in enumerate(body_rows):
            li = body_to_lyric.get(bi)
            row = {**ln, "trans": trans.get(li, "") if li is not None else ""}
            if li is not None and lids.get(li):
                row["lid"] = lids[li]
            if li is not None:
                tokens = tokens_with_spans(ann.get(li), tids.get(li), ln.get("text") or "")
                if tokens:
                    row["tokens"] = tokens
            lines.append(row)
        out = {**doc, "lines": lines, "body_rows": lines,
               "pending": not has_lines and not doc.get("disabled")}
        if rows_extra is not None:
            out.update({"model": 2, "rows": rows_extra})
        return out
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
    if act == "load_rows":
        return LD.load_rows(uid)
    if act == "playback":
        return LD.playback(uid)
    if act == "save_rows":
        return LD.save_rows(uid, req.get("rows") or [],
                            expected_version=req.get("version"),
                            trans_lang=req.get("trans_lang"))
    if act == "edit_reading":
        return LD.edit_reading(uid, req.get("lid"), req.get("tid"),
                               req.get("reading"), expected_version=req.get("version"))
    if act == "export":
        lines = req.get("lines")
        rows = req.get("rows")
        if rows is None and lines and any("kind" in x for x in lines):
            rows = lines
        doc = LRC.load(item["file"], uid, title, artist)
        if rows is not None:
            from ..core.lyric_rows import body_text, render_rows
            return {"ok": True, "nhlrc": render_rows(
                        rows, req.get("trans_lang") or doc.get("trans_lang") or "zh"),
                    "lrc": body_text(rows)}
        if not lines:
            lines = doc.get("body_rows") or doc["lines"]
        from ..core.lyric_rows import body_text, render_rows
        rows = LRC.rows_from_legacy(doc, lines)
        return {"ok": True, "nhlrc": render_rows(
                    rows, doc.get("trans_lang") or "zh"),
                "lrc": body_text(rows)}
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
        if trans is None and any("trans" in ln for ln in lines):
            trans = {i: ln.get("trans") or "" for i, ln in enumerate(lines)}
        return save_lyrics(item, lines, "align", expected_version=req.get("version"),
                           translations=trans)
    return {"ok": False, "error": "未知动作"}

