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




def load_lyrics(item: dict) -> tuple[dict, bool]:
    """普通页与 LRC 编辑共用的唯一歌词入口。"""
    doc = LRC.load(item["file"], item.get("uid"),
                   item["title"], item.get("artist", ""))
    has_lines = any((ln.get("text") or "").strip() for ln in doc["lines"])
    return doc, has_lines


def song_payload(idx: int) -> dict:
    item = CACHE[str(idx)]
    key = item["key"]
    doc, has_lines = load_lyrics(item)
    if not has_lines:
        item["has_lyric"] = False
        return {"idx": str(idx), "key": key, "title": item["title"],
                "artist": item.get("artist", ""), "pending": True, "lines": [],
                "duration": LY.audio_duration(item["file"]),
                "audio": f"/audio/{idx}"}
    item["has_lyric"] = True
    lines = doc["lines"]
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
        "duration": LY.audio_duration(item["file"]),
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
    """重新匹配：候选只来自网络（网易云），不掺本地缓存。"""
    item = CACHE.get(str(idx))
    if not item:
        return {"stem": "", "candidates": []}
    artist, title = LY.split_name(item["stem"])
    duration = float(duration or 0) or LY.audio_duration(item["file"])

    cur = LY.get_lrc(title, artist) or {}
    cur_id = cur.get("id")

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
        if delta is not None and abs(delta) > LY.CFG["fallback_max_delta"]:
            return
        seen.add(c["id"])
        rows.append({"id": c["id"], "name": c.get("name", ""), "artist": c.get("artist", ""),
                     "duration": c.get("duration") or 0, "delta": delta, "source": src,
                     "score": LY.score_candidate(c, title, artist, duration)})

    for c in LY.search_candidates(title, artist):
        add(c, "netease", title)

    for r in rows:
        if cur_id and str(r["id"]) == str(cur_id):
            r["current"] = True

    rows.sort(key=lambda r: (not r.get("current"), -r["score"]))
    return {"stem": item["stem"], "candidates": rows[:10]}


def pick(idx, song_id) -> dict:
    """用户选定候选：用网络歌词替换当前歌词（重写 data/lyrics，读音全部重来）。"""
    item = CACHE.get(str(idx))
    if not item or not song_id:
        return {"ok": False, "error": "缺少歌曲或候选 id"}
    artist, title = LY.split_name(item["stem"])
    lrc = LY.fetch_lrc_by_id(song_id)
    if not lrc or LY.content_lines(lrc) < 3:
        return {"ok": False, "error": "这个候选没有可用歌词"}
    # 重写当前歌曲的 nhlrc 正文（备份旧文件），旧读音不保留
    res = LRC.import_text(item["file"], lrc, item.get("uid"),
                          item["title"], item.get("artist", ""))
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "写歌词失败"}
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
