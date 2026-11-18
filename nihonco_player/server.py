#!/usr/bin/env python3
"""HTTP 路由：只做分发，业务在 library / ruby / lyrics。"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nihonco_yomi.config import PL as PCFG

from . import importing as IMP
from . import song_meta as META
from . import waveform as WAVE
from . import edits as ED
from . import library as LIB
from . import playlists as PL
from . import lrcio as LRC
from . import lyrics as LY
from .library import CACHE
from .web import PAGE

CFG_MERGE_TS = PCFG["merge_same_ts"]

# ── 注音装配（原 ruby.py）──────────────────────────────
import nihonco_yomi
from nihonco_yomi.render import segments_html, words_html
AN = nihonco_yomi.Annotator()
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



def annotate_line_with_notes(text: str, extra_start: int | None = None,
                             extra_reading: str | None = None) -> dict:
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
    return AN.annotate(clean, ov) if ov else base


KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
LAT_RE = re.compile(r"[A-Za-z]")




def song_payload(idx: int) -> dict:
    item = CACHE[str(idx)]
    artist, title = LY.split_name(item["stem"])
    hit = LY.get_lrc(title, artist) or {}
    if not item.get("has_lyric", True):
        return {"idx": str(idx), "key": item["key"], "title": item["title"],
                "artist": item.get("artist", ""), "pending": True, "lines": []}
    edits = ED.for_song(item["key"])
    lines = LY.parse_lrc(hit.get("lrc", ""))
    for li, ln in enumerate(lines):
        if not ln["text"]:
            ln["ruby"], ln["rm"], ln["ky"] = "", "", ""
            continue
        r = annotate_line_with_notes(ln["text"])
        ln["ruby"] = _ruby(r)
        ln["raw"] = ln["text"]
        ln["rm"] = r.get("romaji", {}).get("text", "")
        ln["ky"] = r.get("keys", {}).get("text", "")
        ln["rmH"] = _words(r, "romaji")
        ln["kyH"] = _words(r, "keys")
    return {"idx": idx, "key": item["key"], "title": item["title"], "artist": item["artist"],
            "lines": lines, "edits": edits,
        "offset": float(META.get(item["key"], "offset", 0.0) or 0.0),
        "audio": f"/audio/{idx}",
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _edit(self, idx, li, start, reading):
        item = CACHE.get(str(idx))
        if not item or not reading:
            return None
        artist, title = LY.split_name(item["stem"])
        lines = LY.parse_lrc((LY.get_lrc(title, artist) or {}).get("lrc", ""))
        if not (0 <= li < len(lines)):
            return None
        text = lines[li]["text"]
        clean, _notes = strip_paren_ruby(text)
        base = AN.annotate(clean)
        seg = next((x for x in base["lines"][0]["segments"] if x["start"] == start), None)
        if not seg:
            return None
        r = annotate_line_with_notes(text, extra_start=start, extra_reading=reading)
        return {"line": li, "ruby": _ruby(r), "rm": r.get("romaji", {}).get("text", ""),
                "ky": r.get("keys", {}).get("text", ""),
                "rmH": _words(r, "romaji"), "kyH": _words(r, "keys")}

    # ── 单行编辑 / 重新匹配（原先被误删，重建）──────────────
    def _edit(self, idx, li, start, reading):
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

    def _rematch(self, idx, duration):
        """和首次匹配同一套逻辑：MB 规范化 → 网易云候选 → 按时长打分。"""
        item = CACHE.get(str(idx))
        if not item:
            return {"stem": "", "candidates": []}
        artist, title = LY.split_name(item["stem"])
        duration = float(duration or 0) or LY.audio_duration(item["file"])
        cur = LY.get_lrc(title, artist) or {}

        seen, rows = set(), []

        def add(c, src, q_title):
            if not c or c.get("id") in seen:
                return
            if not LY._match(q_title, c.get("name", "")):
                return
            if src != "current" and LY.is_excluded(c.get("name", "")):
                return
            delta = (round(c["duration"] - duration, 1)
                     if c.get("duration") and duration else None)
            limit = LY.CFG["mb_max_delta"] if src == "mb" else LY.CFG["fallback_max_delta"]
            if src != "current" and delta is not None and abs(delta) > limit:
                return
            seen.add(c.get("id"))
            rows.append({"id": c.get("id"), "name": c.get("name", ""), "artist": c.get("artist", ""),
                         "duration": c.get("duration") or 0, "delta": delta, "source": src,
                         "score": LY.score_candidate(c, title, artist, duration)})

        if cur and not cur.get("miss"):
            add({"id": cur.get("id"), "name": cur.get("name") or title,
                 "artist": cur.get("artist") or artist,
                 "duration": cur.get("duration") or 0}, "current", cur.get("name") or title)
            for r in rows:
                r["current"] = True

        canon = LY.mb_canonical(title, artist, duration)
        queries = {(canon["title"], canon["artist"]) if canon else (title, artist), (title, artist)}
        for q_title, q_artist in queries:
            src = "mb" if canon and (q_title, q_artist) == (canon["title"], canon["artist"]) else "netease"
            for c in LY.search_candidates(q_title, q_artist):
                add(c, src, q_title)

        rows.sort(key=lambda r: (not r.get("current"), -r["score"]))
        return {"stem": item["stem"], "candidates": rows[:10]}

    def _pick(self, idx, song_id) -> bool:
        """用户选定某个候选：把它的歌词写进缓存。"""
        item = CACHE.get(str(idx))
        if not item or not song_id:
            return False
        artist, title = LY.split_name(item["stem"])
        lrc = LY.fetch_lrc_by_id(song_id) if hasattr(LY, "fetch_lrc_by_id") else ""
        if not lrc:
            return False
        LY.write_local_lrc(title, artist, lrc,
                           duration=LY.audio_duration(item["file"]), name=title, by=artist)
        lib = LIB.scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})
        return True

    def _lazy_match(self, item: dict) -> None:
        """按需抓歌词：MB 规范化 + 时长门槛那条流程。"""
        artist, title = LY.split_name(item["stem"])
        LY.get_lrc(title, artist, duration=LY.audio_duration(item["file"]), force=True)
        lib = LIB.scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})

    def _pl(self, req) -> dict:
        """歌单动作：建/改名/删/清空/加/移除/导入。"""
        act = req.get("action")
        if act == "list_create":
            PL.create(str(req.get("name") or "新歌单"))
        elif act == "list_rename":
            PL.rename(str(req.get("id")), str(req.get("name") or ""))
        elif act == "list_delete":
            if not PL.delete(str(req.get("id"))):
                return {"ok": False, "error": "默认歌单不能删除",
                        "lists": PL.build(_cached_items())}
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
            return self._import_to_list(req)
        return {"ok": True, "lists": PL.build(_cached_items())}

    def _import_to_list(self, req) -> dict:
        lid = str(req.get("list"))
        paths = [str(x) for x in (req.get("paths") or [])]
        if not paths:
            return {"ok": False, "error": "没有选择文件", "lists": PL.build(_cached_items())}

        pool = [it["file"] for g in PL.build(_cached_items()) if g["id"] == lid for it in g["items"]]
        res = IMP.import_paths(paths, pool)

        lib = LIB.scan_library()
        CACHE.clear()
        CACHE.update({str(i): x for i, x in enumerate(lib)})
        by_file = {v["file"]: v["uid"] for v in CACHE.values()}
        uids = [by_file[f] for f in res["added"] if f in by_file]
        added_n = PL.add(lid, uids)

        # "待匹配" = 真正进了歌单、但当前还没有歌词的那些
        uids_set = set(uids)
        pending_n = sum(1 for k, v in CACHE.items()
                        if v["uid"] in uids_set and not v.get("has_lyric", True))
        res.update({"ok": True, "library": len(lib), "imported": added_n,
                    "pending_count": pending_n,
                    "already": max(0, len(uids) - added_n)})
        res["lists"] = PL.build(_cached_items())
        return res

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        if urllib.parse.urlparse(self.path).path in ("/api/pl", "/api/playlist"):
            return self._send(200, json.dumps(self._pl(req), ensure_ascii=False))
            return self._send(200, json.dumps(self._lists(req), ensure_ascii=False))
        if req.get("action", "").startswith("list_"):
            return self._send(200, json.dumps(self._lists(req), ensure_ascii=False))
        if req.get("action") == "tag":
            key, tag = str(req.get("key") or ""), str(req.get("tag") or "")
            if not key or tag not in ("inst", "nonja", "wrong"):
                return self._send(400, '{"error":"bad tag"}')
            tags = LIB.load_tags()
            cur = set(tags.get(key, []))
            cur.symmetric_difference_update({tag})
            if cur:
                tags[key] = sorted(cur)
            else:
                tags.pop(key, None)
            LIB.save_tags(tags)
            return self._send(200, json.dumps({"ok": True, "tags": tags.get(key, [])}, ensure_ascii=False))
        if req.get("action") == "rematch":
            return self._send(200, json.dumps(self._rematch(req.get("idx"), req.get("duration")), ensure_ascii=False))
        if req.get("action") == "pick":
            ok = self._pick(req.get("idx"), req.get("id"))
            return self._send(200 if ok else 400, json.dumps({"ok": bool(ok)}))
        if "edits" in req:                      # 批量（恢复本地修改）
            out = []
            for e in req["edits"]:
                r = self._edit(e.get("idx", req.get("idx")), int(e.get("line", -1)),
                               int(e.get("start", -1)), str(e.get("reading") or ""))
                if r:
                    out.append(r)
            return self._send(200, json.dumps({"edits": out}, ensure_ascii=False))
        r = self._edit(req.get("idx"), int(req.get("line", -1)),
                       int(req.get("start", -1)), str(req.get("reading") or ""))
        if not r:
            return self._send(400, '{"error":"bad"}')
        return self._send(200, json.dumps(r, ensure_ascii=False))

    # ── 路由表 ────────────────────────────────────────
    GET = {
        "/api/pl": "_get_playlists",
        "/api/playlists": "_get_playlists",
        "/api/library": "_get_library",
    }
    POST = {
        "/api/pl": "_pl",
        "/api/playlist": "_pl",
        "/api/line": "_post_line",
        "/api/apply": "_post_apply",
        "/api/rematch": "_post_rematch",
        "/api/pick": "_post_pick",
        "/api/tag": "_post_tag",
        "/api/import/one": "_post_import",
        "/api/lrc": "_post_lrc",
    }

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if p.startswith("/static/"):
            return self._static(p)
        if p == "/api/lrc":
            return self._send(404, "POST only")
        if p.startswith("/api/wave/"):
            return self._get_wave(p[len("/api/wave/"):])
        if p.startswith("/api/song/"):
            return self._get_song(p[len("/api/song/"):])
        if p.startswith("/audio/"):
            return self._get_audio(p[len("/audio/"):])
        fn = self.GET.get(p)
        if fn:
            return getattr(self, fn)(p)
        return self._send(404, "not found")

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        fn = self.POST.get(p)
        if not fn:
            return self._send(404, "not found")
        res = getattr(self, fn)(req)
        if isinstance(res, dict):          # 处理器可以直接返回数据
            return self._send(200, json.dumps(res, ensure_ascii=False))
        return res

    # ── 具体处理器 ────────────────────────────────────
    def _static(self, p):
        f = Path(__file__).parent / "static" / p[len("/static/"):]
        if not f.is_file() or ".." in p:
            return self._send(404, "not found")
        ct = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
              ".html": "text/html; charset=utf-8"}.get(f.suffix, "application/octet-stream")
        return self._send(200, f.read_text(encoding="utf-8"), ct)

    def _get_playlists(self, _p):
        lists = PL.build(_cached_items())
        open_ids = PL.load().get("open", [])
        return self._send(200, json.dumps({"lists": lists, "open": open_ids},
                                          ensure_ascii=False))

    def _get_library(self, _p):
        tags = LIB.load_tags()
        HIDE = set() if PCFG.get("show_hidden") else {"inst", "nonja"}
        rows = [{"idx": k, "title": v["title"], "orig": v.get("orig") or v["title"],
                 "artist": v["artist"], "key": v["key"], "group": v.get("group", ""),
                 "tags": tags.get(v["key"], [])}
                for k, v in CACHE.items() if not (set(tags.get(v["key"], [])) & HIDE)]
        return self._send(200, json.dumps(rows, ensure_ascii=False))

    def _get_audio(self, idx):
        """流式返回音频，支持 Range（否则拖动进度条会失效）。"""
        item = CACHE.get(str(idx))
        if not item:
            return self._send(404, "no such song")
        f = Path(item["file"])
        if not f.is_file():
            return self._send(404, "file missing")
        size = f.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                start = int(a) if a else 0
                end = int(b) if b else size - 1
                code = 206
            except ValueError:
                start, end, code = 0, size - 1, 200
        end = min(end, size - 1)
        length = max(0, end - start + 1)
        ctype = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
                 ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg"
                 }.get(f.suffix.lower(), "application/octet-stream")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _get_wave(self, idx):
        item = CACHE.get(str(idx))
        if not item:
            return self._send(404, '{"error":"no such song"}')
        src = "vocals" if item.get("vocals") else "mix"
        data = WAVE.peaks(item["file"], src)
        return self._send(200, json.dumps(data), ctype="application/json; charset=utf-8")

    def _get_song(self, idx):
        try:
            return self._send(200, json.dumps(song_payload(int(idx)), ensure_ascii=False))
        except Exception as e:
            return self._send(404, json.dumps({"error": str(e)}, ensure_ascii=False))

    def _post_line(self, req):
        item = CACHE.get(str(req.get("idx")))
        line = int(req.get("line", -1))
        start = int(req.get("start", -1))
        reading = str(req.get("reading") or "")
        r = self._edit(req.get("idx"), line, start, reading)
        if not r:
            return self._send(400, '{"error":"bad"}')
        if item:
            ED.put(item["key"], line, start, reading)     # 服务端持久化
        return self._send(200, json.dumps(r, ensure_ascii=False))

    def _post_apply(self, req):
        out = []
        for e in req.get("edits", []):
            r = self._edit(e.get("idx", req.get("idx")), int(e.get("line", -1)),
                           int(e.get("start", -1)), str(e.get("reading") or ""))
            if r:
                out.append(r)
        return self._send(200, json.dumps({"edits": out}, ensure_ascii=False))

    def _post_rematch(self, req):
        return self._send(200, json.dumps(self._rematch(req.get("idx"), req.get("duration")),
                                          ensure_ascii=False))

    def _post_pick(self, req):
        ok = self._pick(req.get("idx"), req.get("id"))
        return self._send(200 if ok else 400, json.dumps({"ok": bool(ok)}))

    def _post_import(self, req):
        return self._send(200, json.dumps(self._import_to_list(req), ensure_ascii=False))

    def _post_lrc(self, req):
        item = CACHE.get(str(req.get("idx")))
        if not item:
            return {"ok": False, "error": "没有这首歌"}
        act = req.get("action") or "load"
        if act == "load":
            return LRC.load(item["file"])
        if act == "save":
            lines = req.get("lines") or []
            if not lines:
                return {"ok": False, "error": "没有歌词行"}
            res = LRC.save(item["file"], lines)
            lib = LIB.scan_library()
            CACHE.clear()
            CACHE.update({str(i): x for i, x in enumerate(lib)})
            res["library"] = len(lib)
            return res
        return {"ok": False, "error": "未知动作"}

    def _post_tag(self, req):
        key, tag = str(req.get("key") or ""), str(req.get("tag") or "")
        if not key or tag not in ("inst", "nonja", "wrong"):
            return self._send(400, '{"error":"bad tag"}')
        tags = LIB.load_tags()
        cur = set(tags.get(key, []))
        cur.symmetric_difference_update({tag})
        if cur:
            tags[key] = sorted(cur)
        else:
            tags.pop(key, None)
        LIB.save_tags(tags)
        return self._send(200, json.dumps({"ok": True, "tags": tags.get(key, [])},
                                          ensure_ascii=False))

def _cached_items() -> list[dict]:
    """CACHE 里的条目补上 idx（前端用它调 /api/song/<idx>）。"""
    return [dict(v, idx=k) for k, v in CACHE.items()]


def make_server(port: int = 8766) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), H)


def main() -> None:
    lib = LIB.scan_library()
    CACHE.update({str(i): x for i, x in enumerate(lib)})
    srv = make_server()
    print(f"{len(lib)} 首有歌词 → http://127.0.0.1:{srv.server_address[1]}")
    srv.serve_forever()
