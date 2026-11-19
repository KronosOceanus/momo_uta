#!/usr/bin/env python3
"""歌单 / 导入 / 打标 业务。只依赖 core。"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from ..core import importing as IMP
from ..core import edits as ED
from ..core import library as LIB
from ..core import song_meta as META
from ..core import playlists as PL
from ..core.library import CACHE


def cached_items() -> list[dict]:
    """CACHE 里的条目补上 idx。"""
    return [dict(v, idx=k) for k, v in CACHE.items()]

def playlists_action(req) -> dict:
    """歌单动作：建/改名/删/清空/加/移除/导入。"""
    act = req.get("action")
    if act == "list_create":
        PL.create(str(req.get("name") or "新歌单"))
    elif act == "list_rename":
        if not PL.rename(str(req.get("id")), str(req.get("name") or "")):
            return {"ok": False, "error": "默认歌单不能改名",
                    "lists": PL.build(cached_items())}
    elif act == "list_delete":
        if not PL.delete(str(req.get("id"))):
            return {"ok": False, "error": "默认歌单不能删除",
                    "lists": PL.build(cached_items())}
    elif act == "list_clear":
        PL.clear(str(req.get("id")))
    elif act == "entry_remove":
        PL.remove(str(req.get("list")), str(req.get("uid")))
    elif act == "entry_move":
        PL.move(str(req.get("from")), str(req.get("to")), str(req.get("uid")))
    elif act == "list_reorder":
        PL.reorder_lists([x for x in (req.get("ids") or []) if x])
    elif act == "entry_reorder":
        PL.reorder(str(req.get("list")), [x for x in (req.get("uids") or []) if x])
    elif act == "ui_open":
        PL.set_open([x for x in (req.get("ids") or []) if x])
    elif act == "ui_offset":
        item = CACHE.get(str(req.get("idx")))
        if item:
            META.put(item["key"], offset=round(float(req.get("offset") or 0), 3))
    elif act == "edit_clear":
        item = CACHE.get(str(req.get("idx")))
        if item:
            ED.clear(item["key"])
    elif act == "import":
        return import_to_list(req)
    return {"ok": True, "lists": PL.build(cached_items())}


def import_to_list(req) -> dict:
    lid = str(req.get("list"))
    paths = [str(x) for x in (req.get("paths") or [])]
    if not paths:
        return {"ok": False, "error": "没有选择文件", "lists": PL.build(cached_items())}

    pool = [it["file"] for g in PL.build(cached_items()) if g["id"] == lid for it in g["items"]]
    res = IMP.import_paths(paths, pool)

    # 导入的音频可能不在 music_dirs 里 → 先登记到 imports.json，
    # 再按"路径 → uid"直接算，不依赖这次重扫的结果
    for f in res["added"]:
        p = Path(str(f))
        artist, title = LIB.LY.split_name(p.stem)
        LIB.save_import(str(p), title, artist)
    lib = LIB.scan_library()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
    uids = [hashlib.md5(str(Path(str(f))).encode()).hexdigest()[:12] for f in res["added"]]
    added_n = PL.add(lid, uids)

    # "待匹配" = 真正进了歌单、但当前还没有歌词的那些
    uids_set = set(uids)
    pending_n = sum(1 for k, v in CACHE.items()
                    if v["uid"] in uids_set and not v.get("has_lyric", True))
    res.update({"ok": True, "library": len(lib), "imported": added_n,
                "pending_count": pending_n,
                "already": max(0, len(uids) - added_n)})
    res["lists"] = PL.build(cached_items())
    return res

# ── 路由表 ────────────────────────────────────────

def tag_action(req):
    key, tag = str(req.get("key") or ""), str(req.get("tag") or "")
    if not key or tag not in ("inst", "nonja", "wrong"):
        return {"ok": False, "error": "bad tag"}
    tags = LIB.load_tags()
    cur = set(tags.get(key, []))
    cur.symmetric_difference_update({tag})
    if cur:
        tags[key] = sorted(cur)
    else:
        tags.pop(key, None)
    LIB.save_tags(tags)
    return {"ok": True, "tags": tags.get(key, [])}



def playlists_open() -> list[str]:
    """当前展开的歌单 id（记录在 playlists.json 的 open 字段）。"""
    return PL.load().get("open", [])
