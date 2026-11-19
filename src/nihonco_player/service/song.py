#!/usr/bin/env python3
"""单曲业务：载荷装配、改读音、重新匹配、选候选、懒匹配。

只依赖 core 与引擎；不碰 HTTP。
"""
from __future__ import annotations

import json
import re
import threading

from ..core import library as LIB
from ..core import lrc_files as LRC
from ..core import diag
from ..core import lyrics as LY
from ..core import song_meta as META
from ..core.annotation import (AN, annotations_from_lines,  # noqa: F401
                               annotate_line_with_notes, line_fields, ruby_html,
                               segs_of, strip_paren_ruby, words_html_of)
from ..core.library import CACHE

KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
LAT_RE = re.compile(r"[A-Za-z]")




def song_payload(idx: int) -> dict:
    item = CACHE[str(idx)]
    artist, title = LY.split_name(item["stem"])
    hit = LY.get_lrc(title, artist) or {}
    if not item.get("has_lyric", True):
        return {"idx": str(idx), "key": item["key"], "title": item["title"],
                "artist": item.get("artist", ""), "pending": True, "lines": [],
                "audio": f"/audio/{idx}"}
    key = item["key"]
    doc = LRC.load(item["file"], item.get("uid"), item["title"], item.get("artist", ""))
    lines = doc["lines"]
    if not any((ln.get("text") or "").strip() for ln in lines):
        return {"idx": str(idx), "key": item["key"], "title": item["title"],
                "artist": item.get("artist", ""), "pending": True, "lines": [],
                "audio": f"/audio/{idx}"}
    stored = doc.get("annotations") or {}
    changed = False
    for li, ln in enumerate(lines):
        if not ln["text"]:
            ln["ruby"], ln["rm"], ln["ky"] = "", "", ""
            continue
        fields = line_fields(ln["text"], stored.get(li))
        if li not in stored:
            changed = True
        ln.update(fields)
        ln["raw"] = ln["text"]
    if any((ln.get("text") or "").strip() for ln in lines) and \
            (changed or doc.get("kind") != "nhlrc"):
        try:
            ann = {i: segs_of(annotate_line_with_notes(ln["text"], stored=stored.get(i)))
                   for i, ln in enumerate(lines) if (ln.get("text") or "").strip()}
            LRC.save(item["file"], lines, ann, item.get("uid"), item["title"], item.get("artist", ""))
        except Exception as e:
            diag.log("nhlrc", f"自动落盘失败：{e}")
    return {"idx": idx, "key": key, "title": item["title"], "artist": item["artist"],
            "lines": lines, "nhlrc": True,
        "offset": float(META.get(item["key"], "offset", 0.0) or 0.0),
        "audio": f"/audio/{idx}",
}


def edit_line(idx, li, start, reading):
    """改一处的读音：重算该行、立即写回 nhlrc，返回新 HTML 与罗马音。"""
    item = CACHE.get(str(idx))
    if not item or not reading:
        return None
    with LRC.LOCK:
        doc = LRC.load(item["file"], item.get("uid"), item["title"], item.get("artist", ""))
        lines = doc["lines"]
        if not (0 <= li < len(lines)) or not (lines[li].get("text") or "").strip():
            return None
        text = lines[li]["text"]
        clean, _ = strip_paren_ruby(text)
        base = AN.annotate(clean)
        seg = next((x for x in base["lines"][0]["segments"] if x["start"] == start), None)
        if not seg:
            return None
        ann = dict(doc.get("annotations") or {})
        r = annotate_line_with_notes(text, stored=ann.get(li),
                                     extra_start=start, extra_reading=reading)
        ann[li] = segs_of(r)
        LRC.save(item["file"], lines, ann, item.get("uid"),
                 item["title"], item.get("artist", ""))
    return {"line": li, "ruby": ruby_html(r), "rm": r.get("romaji", {}).get("text", ""),
            "ky": r.get("keys", {}).get("text", ""),
            "rmH": words_html_of(r, "romaji"), "kyH": words_html_of(r, "keys")}


def rematch(idx, duration):
    """重新匹配：候选**完全来自网络**，不拿本地缓存当候选。

    缓存只用来知道"当前正在用哪个 id"，以便在列表里标 ●；
    即使本地改过（缓存即本地编辑结果），网上同一 id 的原版仍会出现，
    选中它就等于用网上版本覆盖本地（覆盖前有 .bak 备份）。
    """
    item = CACHE.get(str(idx))
    if not item:
        return {"stem": "", "candidates": []}
    artist, title = LY.split_name(item["stem"])
    duration = float(duration or 0) or LY.audio_duration(item["file"])

    cur = LY.get_lrc(title, artist) or {}
    cur_id = cur.get("id")
    local_text = cur.get("lrc") or ""
    local_modified = False
    if cur_id and local_text:
        try:
            online = LY.fetch_lrc_by_id(cur_id)
        except Exception:
            online = ""
        if online:
            local_modified = ([x["text"] for x in LY.parse_lrc(online)] !=
                              [x["text"] for x in LY.parse_lrc(local_text)])

    seen, rows = set(), []

    def add(c, src, q_title):
        if not c or not c.get("id") or c["id"] in seen:
            return
        if not LY._match(q_title, c.get("name", "")):
            return
        if LY.is_excluded(c.get("name", "")):
            return
        delta = (round(c["duration"] - duration, 1)
                 if c.get("duration") and duration else None)
        limit = LY.CFG["mb_max_delta"] if src == "mb" else LY.CFG["fallback_max_delta"]
        if delta is not None and abs(delta) > limit:
            return
        seen.add(c["id"])
        rows.append({"id": c["id"], "name": c.get("name", ""), "artist": c.get("artist", ""),
                     "duration": c.get("duration") or 0, "delta": delta, "source": src,
                     "score": LY.score_candidate(c, title, artist, duration)})

    canon = LY.mb_canonical(title, artist, duration)
    queries = {(canon["title"], canon["artist"]) if canon else (title, artist), (title, artist)}
    for q_title, q_artist in queries:
        src = "mb" if canon and (q_title, q_artist) == (canon["title"], canon["artist"]) else "netease"
        for c in LY.search_candidates(q_title, q_artist):
            add(c, src, q_title)

    for r in rows:
        if cur_id and str(r["id"]) == str(cur_id):
            r["current"] = True
            r["local_edit"] = local_modified

    rows.sort(key=lambda r: (not r.get("current"), -r["score"]))
    if cur_id and not any(r.get("current") for r in rows):
        rows.insert(0, {"id": cur_id, "name": cur.get("name") or title,
                        "artist": cur.get("artist") or artist,
                        "duration": cur.get("duration") or 0, "delta": None,
                        "source": "current", "current": True, "local_edit": local_modified,
                        "score": LY.score_candidate({"name": cur.get("name") or title,
                                                     "artist": cur.get("artist") or artist,
                                                     "duration": cur.get("duration") or 0},
                                                    title, artist, duration)})
    return {"stem": item["stem"], "candidates": rows[:10]}


def pick(idx, song_id) -> dict:
    """用户选定某个候选：把它的歌词写进缓存，返回结果。"""
    item = CACHE.get(str(idx))
    if not item or not song_id:
        return {"ok": False, "error": "缺少歌曲或候选 id"}
    artist, title = LY.split_name(item["stem"])
    lrc = LY.fetch_lrc_by_id(song_id)
    if not lrc or LY.content_lines(lrc) < 3:
        return {"ok": False, "error": "这个候选没有可用歌词"}
    LY.write_local_lrc(title, artist, lrc,
                       duration=LY.audio_duration(item["file"]), name=title, by=artist)
    LIB.refresh(item["uid"])
    idx2 = next((k for k, v in CACHE.items() if v["file"] == item["file"]), str(idx))
    d = song_payload(int(idx2))
    return {"ok": True, "idx": idx2, "lines": len(d.get("lines") or [])}

def lazy_match(item: dict) -> None:
    """按需抓歌词：MB 规范化 + 时长门槛那条流程。"""
    artist, title = LY.split_name(item["stem"])
    LY.get_lrc(title, artist, duration=LY.audio_duration(item["file"]), force=True)
    LIB.refresh(item.get("uid"))


# ── HTTP 用得着的两个封装 ─────────────────────────────
def edit_line_action(req) -> dict:
    """改一处读音（HTTP 用）：改完立即写盘；失败返回 {"error"}。"""
    line = int(req.get("line", -1))
    start = int(req.get("start", -1))
    reading = str(req.get("reading") or "")
    r = edit_line(req.get("idx"), line, start, reading)
    if not r:
        return {"error": "读音保存失败"}
    return r
