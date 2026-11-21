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
from ..core import lrc_doc as DOC
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
    return doc, LRC.usable_doc(doc)


def _annotate_lines(lines, stored=None, keep_unchanged=False):
    """按行生成读音；keep_unchanged 时正文没变的行沿用旧标注。"""
    ann = {}
    stored = stored or {}
    for i, ln in enumerate(lines):
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        st = stored.get(i)
        if keep_unchanged and st and "".join(x[0] for x in st) == text:
            ann[i] = st
            continue
        try:
            ann[i] = segs_of(annotate_line_with_notes(text, stored=st))
        except Exception as e:
            diag.log("annotate", f"第 {i} 行注音失败：{e}")
    return ann


def save_lyrics(item: dict, lines=None, mode="align", annotations=None,
                text=None) -> dict:
    """唯一的歌词写入口：处理标注策略、写盘、同步 CACHE。

    mode:
      align      正文没变的行保留旧读音，改字/新行重新注音
      annotated  调用方已经算好 annotations
      replace    换正文（text 或 lines+annotations），旧读音不保留
      reset      正文不变，全部按默认引擎重新注音
    """
    uid = item.get("uid")
    title = item.get("title", "")
    artist = item.get("artist", "")
    if mode == "replace" and text is not None:
        with LRC.LOCK:
            res = LRC.import_text(item["file"], text, uid, title, artist)
    else:
        doc = LRC.load(item["file"], uid, title, artist)
        if mode == "align":
            old = DOC.align_annotations(lines or [], doc.get("annotations") or {})
            ann = _annotate_lines(lines or [], old, keep_unchanged=True)
        elif mode == "annotated":
            ann = annotations or {}
        elif mode == "reset":
            ann = _annotate_lines(lines or [])
        elif mode == "replace":
            ann = annotations or {}
        else:
            raise ValueError("未知歌词保存模式：" + str(mode))
        with LRC.LOCK:
            res = LRC.save(item["file"], lines or [], ann, uid, title, artist)
    if uid:
        res["library"] = LIB.refresh(uid)
        for v in CACHE.values():
            if v.get("uid") == uid:
                v["has_lyric"] = True
                break
    return res


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
            ann = _annotate_lines(lines, stored)
            save_lyrics(item, lines, "annotated", ann)
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
        save_lyrics(item, lines, "annotated", ann)
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
        if not LY.accept_candidate(c, title, artist, duration):
            return
        delta = (round(c["duration"] - duration, 1)
                 if c.get("duration") and duration else None)
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
    return {"stem": item["stem"], "candidates": rows[:int(LY.CFG["manual_limit"])]}


def pick(idx, song_id) -> dict:
    """用户选定候选：用网络歌词替换当前歌词（重写 data/lyrics，读音全部重来）。"""
    item = CACHE.get(str(idx))
    if not item or not song_id:
        return {"ok": False, "error": "缺少歌曲或候选 id"}
    artist, title = LY.split_name(item["stem"])
    lrc = LY.fetch_lrc_by_id(song_id)
    if not LY.valid_lrc(lrc):
        return {"ok": False, "error": "这个候选没有带时间轴的可用歌词"}
    # 重写当前歌曲的 nhlrc 正文（备份旧文件），旧读音不保留
    try:
        res = save_lyrics(item, mode="replace", text=lrc)
    except Exception as e:
        return {"ok": False, "error": "写歌词失败：" + str(e)}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "写歌词失败"}
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
