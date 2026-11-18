#!/usr/bin/env python3
"""歌单：一个歌单就是一串 uid。没有层级、没有目录概念。

数据只有两个字段：
  lists    [{"id","name"}]
  members  {listId: [uid, ...]}
同一首歌可以同时出现在多个歌单里。
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import time
from pathlib import Path

from nihonco_yomi.paths import ROOT

FILE = ROOT / "data" / "curated" / "playlists.json"
DEFAULT_ID = "default"
DEFAULT_NAME = "默认歌单"


def _empty() -> dict:
    return {"lists": [], "members": {}, "list_order": [], "open": []}


def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    out = _empty()
    out["lists"] = [x for x in d.get("lists", []) if x.get("id") and x.get("name")]
    out["members"] = {k: list(v) for k, v in d.get("members", {}).items()}
    out["list_order"] = [x for x in d.get("list_order", []) if isinstance(x, str)]
    out["open"] = [x for x in d.get("open", []) if isinstance(x, str)]
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


@contextlib.contextmanager
def _locked():
    """跨进程互斥：浏览器服务 + 桌面 app 同时开着时，避免互相覆盖。"""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def save(d: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def build(lib: list[dict]) -> list[dict]:
    d = load()
    open_ids = d.get("open", [])
    by_uid = {it["uid"]: it for it in lib}
    # 默认歌单置顶，其余按 list_order（未列出的保持创建顺序）
    order = {lid: i for i, lid in enumerate(d["list_order"])}
    lists = sorted(d["lists"],
                   key=lambda x: (x["id"] != DEFAULT_ID, order.get(x["id"], 10 ** 6)))
    # 不清洗 members：库里暂时找不到的 uid 保留，避免误删歌单内容
    out = []
    for x in lists:
        uids = d["members"].get(x["id"], [])
        out.append({"id": x["id"], "name": x["name"],
                    "items": [by_uid[u] for u in uids if u in by_uid],
                    "missing": sum(1 for u in uids if u not in by_uid),
                    "locked": x["id"] == DEFAULT_ID})
    return out


def create(name: str) -> str:
    with _locked():
        d = load()
        lid = f"user:{int(time.time() * 1000)}"
        d["lists"].append({"id": lid, "name": name})
        d["members"][lid] = []
        save(d)
        return lid



def rename(lid: str, name: str) -> None:
    with _locked():
        d = load()
        for x in d["lists"]:
            if x["id"] == lid:
                x["name"] = name
        save(d)



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
    with _locked():
        d = load()
        d["members"][lid] = [u for u in d["members"].get(lid, []) if u != uid]
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



def move(lid_from: str, lid_to: str, uid: str) -> None:
    with _locked():
        d = load()
        d["members"][lid_from] = [u for u in d["members"].get(lid_from, []) if u != uid]
        seq = d["members"].setdefault(lid_to, [])
        if uid not in seq:
            seq.append(uid)
        save(d)



def reorder(lid: str, uids: list[str]) -> None:
    d = load()
    if lid in d["members"]:
        d["members"][lid] = [u for u in uids if u in d["members"][lid]]
    save(d)
