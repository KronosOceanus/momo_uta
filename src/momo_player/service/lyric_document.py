#!/usr/bin/env python3
"""v2 单一行歌词文档的 service 编排。"""
from __future__ import annotations

from ..core import library as LIB
from ..core import lrc_files as LRC
from ..core import diag
from ..core import fsio as FS
from ..core.lyric_rows import playable as playable_rows


def load_rows(ref) -> dict:
    item = LIB.resolve(ref)
    if not item:
        return {"ok": False, "error": "没有这首歌", "rows": []}
    doc = LRC.load_rows(item["file"], item.get("uid"),
                        item["title"], item.get("artist", ""))
    if not doc.get("ok"):
        return {**doc, "uid": item.get("uid")}
    return {"ok": True, "uid": item.get("uid"), "rows": doc.get("rows") or [],
            "version": doc.get("version"), "exists": bool(doc.get("exists")),
            "model": doc.get("model") or 0,
            "trans_lang": doc.get("trans_lang") or "zh",
            "disabled": bool(doc.get("disabled"))}


def save_rows(ref, rows, expected_version=None, trans_lang=None) -> dict:
    item = LIB.resolve(ref)
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    if trans_lang is None:
        current = LRC.load_rows(item["file"], item.get("uid"),
                                item["title"], item.get("artist", ""))
        trans_lang = current.get("trans_lang") or "zh"
    res = LRC.save_rows(item["file"], rows, uid=item.get("uid"),
                        title=item["title"], artist=item.get("artist", ""),
                        expected_version=expected_version,
                        trans_lang=trans_lang)
    if res.get("ok"):
        try:
            res["library"] = LIB.refresh(item.get("uid"), flush=False)
            res["refresh_ok"] = True
        except Exception as e:
            diag.log("library", f"v2 保存后刷新失败 uid={item.get('uid')}: {e}")
            res["refresh_ok"] = False
            res["refresh_error"] = str(e)
    return res


def edit_reading(ref, lid, tid, reading, expected_version=None) -> dict:
    """v2 手动改读音：同一把锁内按 lid + tid 定位并写入。"""
    item = LIB.resolve(ref)
    if not item:
        return {"ok": False, "error": "没有这首歌"}
    reading = str(reading or "").strip()
    if not reading:
        return {"ok": False, "error": "读音为空"}
    with LRC.LOCK, FS.locked(LRC.lock_path()):
        doc = LRC.load_rows(item["file"], item.get("uid"),
                            item["title"], item.get("artist", ""))
        if not doc.get("ok"):
            return doc
        rows = doc.get("rows") or []
        target = None
        token = None
        for row in rows:
            if row.get("kind") == "lyric" and row.get("lid") == lid:
                target = row
                for tok in row.get("tokens") or []:
                    if tok.get("tid") == tid:
                        token = tok
                        break
                break
        if not target or not token:
            return {"ok": False, "error": "找不到歌词行或 token"}
        token["ruby"] = reading
        token["level"] = "A"
        res = LRC.save_rows(item["file"], rows, uid=item.get("uid"),
                            title=item["title"], artist=item.get("artist", ""),
                            expected_version=(expected_version
                                              if expected_version is not None
                                              else doc.get("version")),
                            trans_lang=doc.get("trans_lang") or "zh")
    if res.get("ok"):
        try:
            res["library"] = LIB.refresh(item.get("uid"), flush=False)
            res["refresh_ok"] = True
        except Exception as e:
            diag.log("library", f"v2 改读音后刷新失败 uid={item.get('uid')}: {e}")
            res["refresh_ok"] = False
            res["refresh_error"] = str(e)
        res["lid"] = lid
        res["tid"] = tid
        res["reading"] = reading
    return res



def playback(ref) -> dict:
    """v2 播放载荷：从 rows 派生可播放行，带 body index。"""
    doc = load_rows(ref)
    if not doc.get("ok"):
        return doc
    if doc.get("disabled"):
        return {"ok": True, "uid": doc.get("uid"), "version": doc.get("version"),
                "disabled": True, "lines": []}
    rows = doc.get("rows") or []
    body_index = {id(row): i for i, row in enumerate(rows)}
    items = playable_rows(rows)
    lines = []
    for row in items:
        lines.append({
            "body_index": body_index.get(id(row)),
            "lid": row.get("lid"),
            "t": row.get("t"),
            "text": row.get("text") or "",
            "tokens": row.get("tokens") or [],
            "trans": row.get("trans") or "",
        })
    return {"ok": True, "uid": doc.get("uid"), "version": doc.get("version"),
            "lines": lines}
