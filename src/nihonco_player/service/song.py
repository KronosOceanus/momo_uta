#!/usr/bin/env python3
"""单曲业务：载荷装配、改读音、重新匹配、选候选、懒匹配。

只依赖 core 与引擎；不碰 HTTP。
"""
from __future__ import annotations

import json
import re
import threading

import nihonco_yomi
from nihonco_yomi.render import segments_html, words_html

from ..core import edits as ED
from ..core import library as LIB
from ..core import lrcio as LRC
from ..core import lyrics as LY
from ..core import song_meta as META
from ..core.library import CACHE

AN = nihonco_yomi.Annotator()
# ── 注音装配（原 ruby.py）──────────────────────────────
RUBY_PAREN = re.compile(r"([\u4e00-\u9fff]+)[（(]([ぁ-んー]+)[）)]")


def _ruby(result) -> str:
    return segments_html(result["lines"][0]["segments"], candidates=True, editable_ab=True)


def _words(result, key: str = "romaji") -> str:
    return words_html(result["lines"][0]["segments"], key)


def strip_paren_ruby(text: str) -> tuple[str, dict]:
    """LRC 里常写成 笑顔(かお)——括号里是实际唱的読み。
    去掉括号，把它记成 override（按"去掉后"的字面位置换算）。"""
    notes = {}
    clean = text
    while True:
        m = RUBY_PAREN.search(clean)
        if not m:
            break
        notes[m.start()] = m.group(2)
        clean = clean[:m.start()] + m.group(1) + clean[m.end():]
    return clean, notes



def _stored_overrides(clean: str, segs: list, stored: list) -> dict | None:
    """把文件里的 [base,ruby,lv] 对齐到引擎片段；对不上返回 None（标注已过期）。"""
    ov, pos = {}, 0
    for item in stored:
        base, ruby = item[0], (item[1] if len(item) > 1 else None)
        if not base:
            return None
        seg = next((x for x in segs if x.get("start") == pos), None)
        if not seg or seg.get("base") != base:
            return None
        if ruby and ruby != (seg.get("ruby") or ""):
            ov[f"o:0-{seg['word']}"] = ruby
        pos += len(base)
    return ov if pos == len(clean) else None


def annotate_line_with_notes(text: str, extra_start: int | None = None,
                             extra_reading: str | None = None,
                             stored: list | None = None) -> dict:
    """标一行：先处理行内注音 笑顔(かお)，再叠加用户改的那一处。

    text 必须是"清洗前"的原文（含括号写法），这样调用方拿到的 start
    与渲染出来的偏移一致。
    """
    clean, notes = strip_paren_ruby(text)
    base = AN.annotate(clean)
    segs = base["lines"][0]["segments"]
    ov = {}
    for start, kana in notes.items():
        seg = next((x for x in segs if x["start"] == start), None)
        if seg:
            ov[f"o:0-{seg['word']}"] = kana
    if extra_start is not None and extra_reading:
        seg = next((x for x in segs if x["start"] == extra_start), None)
        if seg:
            ov[f"o:0-{seg['word']}"] = extra_reading
    if stored:
        got = _stored_overrides(clean, segs, stored)
        if got is not None:
            ov.update({k: v for k, v in got.items() if v})
    return AN.annotate(clean, ov) if ov else base


def segs_of(result) -> list:
    """引擎结果 → 文件里存的紧凑形式 [[base, ruby, level], …]"""
    return [[seg["base"], seg.get("ruby"), seg.get("level")]
            for seg in result["lines"][0]["segments"]]


def annotations_from_lines(lines: list[dict]) -> dict[int, list]:
    """按当前行内容重新注音，生成 nhlrc 的标注表。"""
    out: dict[int, list] = {}
    for i, ln in enumerate(lines):
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        try:
            out[i] = segs_of(annotate_line_with_notes(text))
        except Exception:
            pass
    return out


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
    edits = ED.for_song(item["key"])
    doc = LRC.load(item["file"])
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
        r = annotate_line_with_notes(ln["text"], stored=stored.get(li))
        if li not in stored:
            changed = True
        ln["ruby"] = _ruby(r)
        ln["raw"] = ln["text"]
        ln["rm"] = r.get("romaji", {}).get("text", "")
        ln["ky"] = r.get("keys", {}).get("text", "")
        ln["rmH"] = _words(r, "romaji")
        ln["kyH"] = _words(r, "keys")
    if changed and any((ln.get("text") or "").strip() for ln in lines):
        try:
            ann = {i: segs_of(annotate_line_with_notes(ln["text"], stored=stored.get(i)))
                   for i, ln in enumerate(lines) if (ln.get("text") or "").strip()}
            if doc.get("kind") in ("lrc", "nhlrc"):
                LRC.save(item["file"], lines, ann)          # 有本地歌词文件 → 写 .nhlrc
            else:
                LY.write_local_lrc(title, artist, doc["text"], annotations=ann,
                                   duration=LY.audio_duration(item["file"]),
                                   name=title, by=artist)   # 纯缓存 → 标注存缓存
        except Exception:
            pass
    return {"idx": idx, "key": item["key"], "title": item["title"], "artist": item["artist"],
            "lines": lines, "edits": edits, "nhlrc": True,
        "offset": float(META.get(item["key"], "offset", 0.0) or 0.0),
        "audio": f"/audio/{idx}",
}


def edit_line(idx, li, start, reading):
    """改一处的读音：返回该行的新 HTML 与罗马音。"""
    item = CACHE.get(str(idx))
    if not item or not reading:
        return None
    artist, title = LY.split_name(item["stem"])
    lines = LY.parse_lrc((LY.get_lrc(title, artist) or {}).get("lrc") or "")
    if not (0 <= li < len(lines)):
        return None
    text = lines[li].text if hasattr(lines[li], "text") else lines[li]["text"]
    clean, _ = strip_paren_ruby(text)
    base = AN.annotate(clean)
    seg = next((x for x in base["lines"][0]["segments"] if x["start"] == start), None)
    if not seg:
        return None
    r = annotate_line_with_notes(text, extra_start=start, extra_reading=reading)
    return {"line": li, "ruby": _ruby(r), "rm": r.get("romaji", {}).get("text", ""),
            "ky": r.get("keys", {}).get("text", ""),
            "rmH": _words(r, "romaji"), "kyH": _words(r, "keys")}

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
    lib = LIB.scan_library()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
    idx2 = next((k for k, v in CACHE.items() if v["file"] == item["file"]), str(idx))
    d = song_payload(int(idx2))
    return {"ok": True, "idx": idx2, "lines": len(d.get("lines") or [])}

def lazy_match(item: dict) -> None:
    """按需抓歌词：MB 规范化 + 时长门槛那条流程。"""
    artist, title = LY.split_name(item["stem"])
    LY.get_lrc(title, artist, duration=LY.audio_duration(item["file"]), force=True)
    lib = LIB.scan_library()
    CACHE.clear()
    CACHE.update({str(i): x for i, x in enumerate(lib)})


# ── HTTP 用得着的两个封装 ─────────────────────────────
def edit_line_action(req) -> dict:
    """改一处读音（HTTP 用）：成功返回新行，失败返回 {"error"}。"""
    item = CACHE.get(str(req.get("idx")))
    line = int(req.get("line", -1))
    start = int(req.get("start", -1))
    reading = str(req.get("reading") or "")
    r = edit_line(req.get("idx"), line, start, reading)
    if not r:
        return {"error": "bad"}
    if item:
        ED.put(item["key"], line, start, reading)
    return r


def apply_edits(req) -> dict:
    """批量恢复读音（打开一首歌时用）。"""
    out = []
    for e in req.get("edits", []):
        r = edit_line(e.get("idx", req.get("idx")), int(e.get("line", -1)),
                      int(e.get("start", -1)), str(e.get("reading") or ""))
        if r:
            out.append(r)
    return {"edits": out}
