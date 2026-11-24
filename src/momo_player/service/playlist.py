#!/usr/bin/env python3
"""歌单 / 导入 / 打标 业务。只依赖 core。"""
from __future__ import annotations

from pathlib import Path

from ..core import importing as IMP
from ..core import lrc_files as LRC
from ..core import fingerprint as FP
from ..core import library as LIB
from ..core import song_meta as META
from ..core import playlists as PL
from . import song as SONGS


def cached_items() -> list[dict]:
    """CACHE 里的条目补上 idx（快照，避免发布中读到半套）。"""
    return [dict(v, idx=k) for k, v in LIB.snapshot()]


def _lists():
    return PL.build(cached_items())

def playlists_action(req) -> dict:
    """歌单动作：建/改名/删/清空/加/移除/导入。"""
    act = req.get("action")
    if act in ("ui_offset", "edit_clear", "match") and not req.get("uid"):
        return {"ok": False, "error": "缺少 uid", "lists": _lists()}
    if act == "list_create":
        PL.create(str(req.get("name") or "新歌单"))
    elif act == "list_rename":
        if not PL.rename(str(req.get("id")), str(req.get("name") or "")):
            return {"ok": False, "error": "默认歌单不能改名", "lists": _lists()}
    elif act == "list_delete":
        if not PL.delete(str(req.get("id"))):
            return {"ok": False, "error": "默认歌单不能删除", "lists": _lists()}
    elif act == "list_clear":
        PL.clear(str(req.get("id")))
    elif act == "entry_remove":
        lid = str(req.get("list") or req.get("from") or "")
        uid = str(req.get("uid") or "")
        if lid and uid:
            PL.remove(lid, uid)
    elif act == "entries_remove":
        lid = str(req.get("list") or req.get("from") or "")
        uids = [str(x) for x in (req.get("uids") or []) if x]
        if lid and uids:
            PL.remove_many(lid, uids)
    elif act == "entry_move":
        PL.move(str(req.get("from")), str(req.get("to")), str(req.get("uid")))
    elif act == "entries_move":
        PL.move_many(str(req.get("from")), str(req.get("to")),
                     [str(x) for x in (req.get("uids") or []) if x],
                     str(req.get("before") or "") or None)
    elif act == "list_reorder":
        PL.reorder_lists([x for x in (req.get("ids") or []) if x])
    elif act == "entry_reorder":
        PL.reorder(str(req.get("list")), [x for x in (req.get("uids") or []) if x])
    elif act == "ui_open":
        PL.set_open([x for x in (req.get("ids") or []) if x])
    elif act == "ui_offset":
        item = LIB.resolve(req.get("uid"))
        if not item:
            return {"ok": False, "error": "歌曲已不可用，请重新加载", "lists": _lists()}
        META.put(item["uid"], offset=round(float(req.get("offset") or 0), 3))
    elif act == "edit_clear":
        item = LIB.resolve(req.get("uid"))
        if not item:
            return {"ok": False, "error": "歌曲已不可用，请重新加载", "lists": _lists()}
        doc = LRC.load(item["file"], item.get("uid"),
                       item["title"], item.get("artist", ""))
        if doc.get("disabled"):
            return {"ok": False, "error": "歌词已禁用，请重新匹配或导入",
                    "lists": _lists()}
        r = SONGS.save_lyrics(item, None, "reset",
                              expected_version=req.get("version"))
        if not r.get("ok"):
            return {**r, "lists": _lists()}
        return {"ok": True, "lists": _lists(), "version": r.get("version")}
    elif act == "match":
        item = LIB.resolve(req.get("uid"))
        if not item:
            return {"ok": False, "error": "歌曲已不可用，请重新加载", "lists": _lists()}
        SONGS.lazy_match(item)
    elif act == "import":
        return import_to_list(req)
    elif act == "library_rebuild":
        if not LIB.LAST_MISSING:               # 没有缺失就不重建
            return {"ok": True, "library": len(LIB.snapshot()), "missing": 0, "recovered": 0,
                    "lists": _lists(), "missing_count": 0}
        r = LIB.rebuild_library()
        return {**r, "lists": _lists(),
                "missing_count": len(LIB.LAST_MISSING)}
    return {"ok": True, "lists": _lists(),
            "missing_count": len(LIB.LAST_MISSING),
            "auto_rebuild": LIB.should_auto_rebuild()}


def import_to_list(req) -> dict:
    lid = str(req.get("list") or "")
    paths = [str(x) for x in (req.get("paths") or [])]
    if not paths:
        return {"ok": False, "error": "没有选择文件", "lists": _lists()}
    if not PL.exists(lid):
        return {"ok": False, "error": "歌单不存在", "lists": _lists()}

    pool = [it["file"] for g in PL.build(cached_items()) if g["id"] == lid for it in g["items"]]
    res = IMP.import_paths(paths, pool, with_lrc=bool(req.get("with_lrc")))

    # 导入的音频可能不在 music_dirs 里 → 先登记到 imports.json，
    # 再只把新增文件加进 CACHE，不动已有 idx、不扫全库。
    for f in res["added"]:
        p = Path(str(f))
        artist, title = LIB.LY.split_name(p.stem)
        LIB.save_import(str(p), title, artist)
    LIB.add_paths(res["added"], "导入")

    # 以曲库实际存在的 uid 为准；不能把未进入 CACHE 的 uid 写进歌单。
    uids = []
    for f in dict.fromkeys(str(x) for x in res["added"]):
        uid = FP.fingerprint(f)
        if LIB.resolve(uid):
            uids.append(uid)
        else:
            res.setdefault("failed", []).append(
                {"audio": f, "error": "文件未进入曲库"})
    try:
        added_n = PL.add(lid, uids)
    except Exception as e:
        return {"ok": False, "error": f"加入歌单失败：{e}",
                "library": len(LIB.snapshot()), "lists": _lists(),
                "failed": (res.get("failed") or [])[:5],
                "failed_count": len(res.get("failed") or [])}
    library_n = len(LIB.snapshot())

    # "待匹配" = 真正进了歌单、但当前还没有歌词的那些
    uids_set = set(uids)
    pending_n = sum(1 for k, v in LIB.snapshot()
                    if v["uid"] in uids_set and not v.get("has_lyric", True))
    failed = res.get("failed") or []
    res.update({"ok": True, "library": library_n, "imported": added_n,
                "pending_count": pending_n,
                "failed": failed[:5],
                "failed_count": len(failed),
                "already": max(0, len(uids) - added_n)})
    res["lists"] = _lists()
    return res

# ── 路由表 ────────────────────────────────────────

def playlists_open() -> list[str]:
    """当前展开的歌单 id（记录在 playlists.json 的 open 字段）。"""
    return PL.load().get("open", [])
