#!/usr/bin/env python3
"""HTTP 层：只做解析与转发，业务全在 service/。"""
from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

from ..core import library as LIB
from ..core import lyrics as LY
from ..core.library import CACHE
from ..web import PAGE
from ..service import lrc as SVC_LRC
from ..service import playlist as SVC_PL
from ..service import song as SVC_SONG
from . import static as STATIC


class H(BaseHTTPRequestHandler):
    GET = {
        "/api/pl": "_get_playlists",
        "/api/playlists": "_get_playlists",
        "/api/library": "_get_library",
    }
    POST = {
        "/api/pl": "_post_pl",
        "/api/playlist": "_post_pl",
        "/api/line": "_post_line",
        "/api/apply": "_post_apply",
        "/api/rematch": "_post_rematch",
        "/api/pick": "_post_pick",
        "/api/tag": "_post_tag",
        "/api/import/one": "_post_import",
        "/api/lrc": "_post_lrc",
        "/api/vocals": "_post_vocals",
        "/api/debug": "_post_debug",
    }

    # ── 基础 ─────────────────────────────────────────
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

    def _json(self, obj, code=200):
        return self._send(code, json.dumps(obj, ensure_ascii=False))

    # ── 分发 ─────────────────────────────────────────
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if p.startswith("/static/"):
            it = STATIC.static_file(p)
            return self._send(200, it[0], it[1]) if it else self._send(404, "not found")
        if p.startswith("/api/song/"):
            return self._get_song(p[len("/api/song/"):])
        if p.startswith("/audio/"):
            return self._get_audio(p[len("/audio/"):])
        if p.startswith("/api/wave/"):
            return self._get_wave(p[len("/api/wave/"):])
        if p.startswith("/api/vocals/"):
            return self._get_vocals(p[len("/api/vocals/"):])
        fn = self.GET.get(p)
        return getattr(self, fn)() if fn else self._send(404, "not found")

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        fn = self.POST.get(p)
        return getattr(self, fn)(req) if fn else self._send(404, "not found")

    # ── GET ──────────────────────────────────────────
    def _get_playlists(self):
        lists = SVC_PL.playlists_action({"action": "noop"})["lists"]
        return self._json({"lists": lists, "open": SVC_PL.playlists_open()})

    def _get_library(self):
        tags = LIB.load_tags()
        # 不再隐藏任何歌：标签只作为展示信息
        rows = [{"idx": k, "title": v["title"], "orig": v.get("orig") or v["title"],
                 "artist": v["artist"], "key": v["key"], "group": v.get("group", ""),
                 "tags": tags.get(v["key"], [])}
                for k, v in CACHE.items()]
        return self._json(rows)

    def _get_song(self, idx):
        try:
            return self._json(SVC_SONG.song_payload(int(idx)))
        except Exception as e:
            return self._json({"error": str(e)}, 404)

    def _get_wave(self, idx):
        from ..core import waveform as WAVE
        from ..core import vocals as VOC
        q = urllib.parse.urlparse(self.path).query
        want = urllib.parse.parse_qs(q).get("src", ["mix"])[0]
        item = CACHE.get(str(idx))
        if not item:
            return self._json({"error": "no such song"}, 404)
        if want == "vocals":
            _, wav, _ = VOC.paths(item["uid"])
            if wav.is_file():
                out = WAVE.peaks(str(wav), "vocals")
                out["source"] = "vocals"
                return self._json(out)
        out = WAVE.peaks(item["file"], "mix")
        out["source"] = "mix"
        return self._json(out)

    def _get_vocals(self, idx):
        from ..core import vocals as VOC
        item = CACHE.get(str(idx))
        if not item:
            return self._json({"error": "no such song"}, 404)
        return self._json(VOC.status(item["uid"]))

    def _post_vocals(self, req):
        from ..core import vocals as VOC
        item = CACHE.get(str(req.get("idx")))
        if not item:
            return self._json({"ok": False, "error": "no such song"}, 404)
        return self._json(VOC.ensure(item["uid"], item["file"]))

    def _get_audio(self, idx):
        item = CACHE.get(str(idx))
        if not item:
            return self._send(404, "no such song")
        info = STATIC.audio_info(item["file"], self.headers.get("Range"))
        if not info:
            return self._send(404, "file missing")
        code, start, end, size, ctype, crange = info
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if crange:
            self.send_header("Content-Range", crange)
        self.end_headers()
        with open(item["file"], "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ── POST ─────────────────────────────────────────
    def _post_pl(self, req):
        return self._json(SVC_PL.playlists_action(req))

    def _post_import(self, req):
        return self._json(SVC_PL.import_to_list(req))

    def _post_tag(self, req):
        r = SVC_PL.tag_action(req)
        return self._json(r, 200 if r.get("ok") else 400)

    def _post_line(self, req):
        return self._json(SVC_SONG.edit_line_action(req))

    def _post_apply(self, req):
        return self._json(SVC_SONG.apply_edits(req))

    def _post_rematch(self, req):
        return self._json(SVC_SONG.rematch(req.get("idx"), req.get("duration")))

    def _post_pick(self, req):
        r = SVC_SONG.pick(req.get("idx"), req.get("id"))
        return self._json(r, 200 if r.get("ok") else 400)

    def _post_lrc(self, req):
        return self._json(SVC_LRC.lrc_action(req))

    def _post_debug(self, req):
        """前端诊断数据 → data/cache/app.log（只用于排查卡顿，可随时删除）"""
        import time
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        log = root / "data" / "cache" / "app.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"[js] {time.strftime('%H:%M:%S')} "
                     f"{req.get('kind','')} {req.get('data','')}\n")
        return self._json({"ok": True})
