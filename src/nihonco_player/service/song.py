#!/usr/bin/env python3
"""单曲业务：载荷装配、改读音、重新匹配、选候选、懒匹配。

只依赖 core 与引擎；不碰 HTTP。
"""
from __future__ import annotations

import json
import re
import threading

from ..core import annotation_cache as ANN_CACHE
from ..core import library as LIB
from ..core import lrc_files as LRC
from ..core import lrc_doc as DOC
from ..core import diag
from ..core import fsio as FS
from ..core import lyrics as LY
from ..core import song_meta as META
from ..core.annotation import (AN, annotations_from_lines,  # noqa: F401
                               annotate_line_with_notes, ruby_html,
                               segs_of, strip_paren_ruby, words_html_of)

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
                text=None, expected_version=None, translations=None,
                trans_lang="zh") -> dict:
    """唯一的歌词权威写入口：锁内读改写 + 版本校验 + 原子替换。

    mode:
      align      正文没变的行保留旧读音，改字/新行重新注音
      annotated  调用方已经算好 annotations
      replace    换正文（text 或 lines+annotations），旧读音不保留
      reset      正文不变，全部按默认引擎重新注音
    """
    uid = item.get("uid")
    title = item.get("title", "")
    artist = item.get("artist", "")
    with LRC.LOCK, FS.locked(LRC.lock_path()):
        if mode == "replace" and text is not None:
            res = LRC.import_text(item["file"], text, uid, title, artist,
                                  expected_version=expected_version,
                                  translations=translations,
                                  trans_lang=trans_lang)
        else:
            doc = LRC.load(item["file"], uid, title, artist)
            if mode == "align":
                old = DOC.align_annotations(lines or [], doc.get("annotations") or {})
                ann = _annotate_lines(lines or [], old, keep_unchanged=True)
            elif mode == "annotated":
                ann = annotations or {}
            elif mode == "reset":
                if lines is None:
                    lines = doc.get("lines") or []
                ann = _annotate_lines(lines)
            elif mode == "replace":
                ann = annotations or {}
            else:
                raise ValueError("未知歌词保存模式：" + str(mode))
            if translations is None:
                if any("trans" in x for x in (lines or [])):
                    translations = {i: x.get("trans") or ""
                                    for i, x in enumerate(lines or [])}
                else:
                    translations = doc.get("translations") or {}
            trans = DOC.align_translations(lines or [], doc.get("lines") or [],
                                           translations)
            res = LRC.save(item["file"], lines or [], ann, uid=uid, title=title,
                           artist=artist, expected_version=expected_version,
                           translations=trans, trans_lang=trans_lang)
    if uid and res.get("ok"):
        try:
            res["library"] = LIB.refresh(uid)
            for _, v in LIB.snapshot():
                if v.get("uid") == uid:
                    v["has_lyric"] = True
                    break
            res["refresh_ok"] = True
        except Exception as e:
            # 写入已经成功；刷新失败不能伪装成"歌词没保存"
            diag.log("library", f"保存后刷新失败 uid={uid}: {e}")
            res["refresh_ok"] = False
            res["refresh_error"] = str(e)
    return res


def _payload_base(item: dict, idx, uid, doc: dict) -> dict:
    """所有分支共用的载荷字段；idx 只做展示，统一为字符串或 None。"""
    return {
        "uid": uid,
        "idx": None if idx is None else str(idx),
        "key": item["key"],
        "title": item["title"],
        "artist": item.get("artist", ""),
        "version": doc.get("version"),
        "duration": LY.audio_duration(item["file"]),
        "audio": f"/audio/{uid}",
        "offset": float(META.get(uid, "offset", 0.0) or 0.0),
    }


def song_payload(ref, _item=None) -> dict:
    item = _item or LIB.resolve(ref)
    if not item:
        raise KeyError("没有这首歌")
    uid = item.get("uid")
    idx = LIB.idx_for(uid or ref)
    doc, has_lines = load_lyrics(item)
    base = _payload_base(item, idx, uid, doc)
    if doc.get("disabled"):
        item["has_lyric"] = False
        return {**base, "pending": False, "disabled": True,
                "lines": [], "nhlrc": False}
    if not has_lines:
        item["has_lyric"] = False
        return {**base, "pending": True, "disabled": False, "lines": [],
                "nhlrc": doc.get("kind") == "nhlrc"}
    item["has_lyric"] = True
    lines = doc["lines"]
    stored = doc.get("annotations") or {}
    for li, ln in enumerate(lines):
        if not ln["text"]:
            ln["ruby"], ln["rm"], ln["ky"] = "", "", ""
            continue
        fields = ANN_CACHE.line_fields(ln["text"], stored.get(li))
        ln.update(fields)
        ln["raw"] = ln["text"]
        ln["trans"] = ((doc.get("translations") or {}).get(li) or "")
    return {**base, "pending": False, "lines": lines,
            "nhlrc": doc.get("kind") == "nhlrc", "disabled": False}


def edit_line(uid, li, start, reading):
    """改一处的读音：重算该行、立即写回 nhlrc，返回新 HTML 与罗马音。"""
    item = LIB.resolve(uid)
    if not item or not reading:
        return None
    with LRC.LOCK, FS.locked(LRC.lock_path()):
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
        res = save_lyrics(item, lines, "annotated", ann)
        if not res.get("ok"):
            return None
    return {"line": li, "ruby": ruby_html(r), "rm": r.get("romaji", {}).get("text", ""),
            "ky": r.get("keys", {}).get("text", ""),
            "rmH": words_html_of(r, "romaji"), "kyH": words_html_of(r, "keys"),
            "version": res.get("version")}


def rematch(ref, duration):
    """重新匹配：候选只来自网络（网易云），不掺本地缓存。"""
    item = LIB.resolve(ref)
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


def pick(uid, song_id) -> dict:
    """用户选定候选：用网络歌词替换当前歌词（重写 data/lyrics，读音全部重来）。"""
    item = LIB.resolve(uid)
    if not item or not song_id:
        return {"ok": False, "error": "缺少歌曲或候选 id"}
    artist, title = LY.split_name(item["stem"])
    hit = LY.fetch_lyrics_by_id(song_id)
    lrc = hit.get("lrc") or ""
    if not LY.valid_lrc(lrc):
        return {"ok": False, "error": "这个候选没有带时间轴的可用歌词"}
    trans = DOC.translations_from_lrc(hit.get("tlyric") or "", DOC.parse(lrc))
    # 重写当前歌曲的 nhlrc 正文（备份旧文件），旧读音不保留
    try:
        res = save_lyrics(item, mode="replace", text=lrc, translations=trans)
    except Exception as e:
        return {"ok": False, "error": "写歌词失败：" + str(e)}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "写歌词失败"}
    d = song_payload(None, item)   # 用刚保存的同一份条目回读，不再回查 idx
    return {"ok": True, "uid": item.get("uid"), "idx": d.get("idx"),
            "lines": len(d.get("lines") or [])}

def lazy_match(item: dict) -> None:
    """按需抓歌词；明确禁用歌词的歌不联网。"""
    if LRC.load(item["file"], item.get("uid"), item.get("title"), item.get("artist", "")).get("disabled"):
        return
    artist, title = LY.split_name(item["stem"])
    LY.get_lrc(title, artist, duration=LY.audio_duration(item["file"]), force=True)
    LIB.refresh(item.get("uid"))


# ── HTTP 用得着的两个封装 ─────────────────────────────
def edit_line_action(req) -> dict:
    """改一处读音（HTTP 用）：改完立即写盘；失败返回 {"error"}。"""
    line = int(req.get("line", -1))
    start = int(req.get("start", -1))
    reading = str(req.get("reading") or "")
    r = edit_line(req.get("uid"), line, start, reading)
    if not r:
        return {"error": "读音保存失败"}
    return r
