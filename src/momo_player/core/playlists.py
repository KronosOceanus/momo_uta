#!/usr/bin/env python3
"""歌单：一个歌单就是一串 uid。没有层级、没有目录概念。

数据只有两个字段：
  lists    [{"id","name"}]
  members  {listId: [uid, ...]}
同一首歌可以同时出现在多个歌单里。
"""
from __future__ import annotations

import time

from momo_yomi.paths import ROOT

from . import fsio as FS

FILE = ROOT / "data" / "curated" / "playlists.json"
DEFAULT_ID = "default"
DEFAULT_NAME = "默认歌单"


def _empty() -> dict:
    return {"lists": [], "members": {}, "list_order": [], "open": []}


def load() -> dict:
    """读歌单；坏条目逐条丢弃，不因为一个坏 record 丢掉全部。"""
    d = FS.read_json(FILE, {}) or {}
    if not isinstance(d, dict):
        d = {}
    out = _empty()

    raw_lists = d.get("lists")
    seen = set()
    if isinstance(raw_lists, list):
        for x in raw_lists:
            if not isinstance(x, dict):
                continue
            lid = x.get("id")
            name = x.get("name")
            if not isinstance(lid, str) or not lid:
                continue
            if not isinstance(name, str) or not name:
                continue
            if lid in seen:
                continue
            seen.add(lid)
            out["lists"].append({"id": lid, "name": name})

    raw_members = d.get("members")
    if isinstance(raw_members, dict):
        for lid, seq in raw_members.items():
            if not isinstance(lid, str) or not lid:
                continue
            if not isinstance(seq, list):
                continue
            uids = [u for u in seq if isinstance(u, str) and u]
            out["members"][lid] = list(dict.fromkeys(uids))

    raw_order = d.get("list_order")
    if isinstance(raw_order, list):
        out["list_order"] = [x for x in raw_order if isinstance(x, str) and x]

    raw_open = d.get("open")
    if isinstance(raw_open, list):
        out["open"] = [x for x in raw_open if isinstance(x, str) and x]

    if not any(x["id"] == DEFAULT_ID for x in out["lists"]):
        out["lists"].insert(0, {"id": DEFAULT_ID, "name": DEFAULT_NAME})
    out["members"].setdefault(DEFAULT_ID, [])
    return out


LOCK = FILE.with_suffix(".lock")


def set_file(path) -> None:
    """换数据文件（测试用）。"""
    global FILE, LOCK
    from pathlib import Path as _P
    FILE = _P(path)
    LOCK = FILE.with_suffix(".lock")


def _locked():
    """跨进程互斥：浏览器服务 + 桌面 app 同时开着时，避免互相覆盖。"""
    return FS.locked(LOCK)


def save(d: dict) -> None:
    FS.atomic_write_json(FILE, d, indent=1)


def all_uids() -> list[str]:
    """所有歌单成员 uid（去重，保持出现顺序）。"""
    d = load()
    out: list[str] = []
    for seq in d.get("members", {}).values():
        out.extend(x for x in seq if x)
    return list(dict.fromkeys(out))


def build(lib: list[dict]) -> list[dict]:
    d = load()
    by_uid = {it["uid"]: it for it in lib}
    # 默认歌单置顶，其余按 list_order（未列出的保持创建顺序）
    order = {lid: i for i, lid in enumerate(d["list_order"])}
    lists = sorted(d["lists"],
                   key=lambda x: (x["id"] != DEFAULT_ID, order.get(x["id"], 10 ** 6)))
    # 不清洗 members：库里暂时找不到的 uid 保留，避免误删歌单内容
    out = []
    for x in lists:
        uids = d["members"].get(x["id"], [])
        items, missing = [], 0
        for u in uids:
            it = by_uid.get(u)
            if not it:
                missing += 1
                continue
            items.append(it)
        out.append({"id": x["id"], "name": x["name"], "items": items,
                    "missing": missing, "locked": x["id"] == DEFAULT_ID})
    return out


def create(name: str) -> str:
    with _locked():
        d = load()
        lid = f"user:{int(time.time() * 1000)}"
        d["lists"].append({"id": lid, "name": name})
        d["members"][lid] = []
        save(d)
        return lid



def rename(lid: str, name: str) -> bool:
    """改名；默认歌单锁定，不允许改。"""
    if lid == DEFAULT_ID:
        return False
    with _locked():
        d = load()
        for x in d["lists"]:
            if x["id"] == lid:
                x["name"] = name
        save(d)
    return True



def delete(lid: str) -> bool:
    with _locked():
        if lid == DEFAULT_ID:
            return False                       # 默认歌单不能删
        d = load()
        d["lists"] = [x for x in d["lists"] if x["id"] != lid]
        d["members"].pop(lid, None)
        save(d)
        return True



def clear(lid: str) -> None:
    with _locked():
        d = load()
        d["members"][lid] = []
        save(d)



def add(lid: str, uids: list[str]) -> int:
    with _locked():
        d = load()
        seq = d["members"].setdefault(lid, [])
        n = 0
        for u in uids:
            if u and u not in seq:
                seq.append(u)
                n += 1
        save(d)
        return n



def remove(lid: str, uid: str) -> None:
    remove_many(lid, [uid])


def remove_many(lid: str, uids: list[str]) -> None:
    drop = {str(u) for u in uids if u}
    if not drop:
        return
    with _locked():
        d = load()
        d["members"][lid] = [u for u in d["members"].get(lid, []) if u not in drop]
        save(d)



def set_open(ids: list[str]) -> None:
    with _locked():
        d = load()
        d["open"] = [x for x in ids if x]
        save(d)


def reorder_lists(ids: list[str]) -> None:
    with _locked():
        d = load()
        d["list_order"] = [x for x in ids if x and x != DEFAULT_ID]
        save(d)



def move_many(lid_from: str, lid_to: str, uids: list[str],
              before: str | None = None) -> None:
    """批量移动；before 是目标歌单里插到它前面的 uid。"""
    moved = [u for u in dict.fromkeys(str(x) for x in uids if x)]
    if not moved or not lid_from or not lid_to:
        return
    with _locked():
        d = load()
        src = d["members"].get(lid_from, [])
        moved = [u for u in moved if u in src]
        if not moved:
            return
        moved_set = set(moved)
        base = [u for u in src if u not in moved_set]
        dst = base if lid_from == lid_to else [
            u for u in d["members"].get(lid_to, []) if u not in moved_set]
        at = dst.index(before) if before in dst else len(dst)
        dst[at:at] = moved
        if lid_from != lid_to:
            d["members"][lid_from] = base
        d["members"][lid_to] = dst
        save(d)


def move(lid_from: str, lid_to: str, uid: str) -> None:
    with _locked():
        d = load()
        d["members"][lid_from] = [u for u in d["members"].get(lid_from, []) if u != uid]
        seq = d["members"].setdefault(lid_to, [])
        if uid not in seq:
            seq.append(uid)
        save(d)



def reorder(lid: str, uids: list[str]) -> None:
    with _locked():
        d = load()
        if lid in d["members"]:
            d["members"][lid] = [u for u in uids if u in d["members"][lid]]
        save(d)
