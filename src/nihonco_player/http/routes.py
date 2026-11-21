#!/usr/bin/env python3
"""HTTP 层：只做解析与转发，业务全在 service/。"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

from ..core import diag
from ..core import lyrics as LY
from ..core import library as LIB
from ..web import PAGE
from ..service import jobs as SVC_JOBS
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
        "/api/rematch": "_post_rematch",
        "/api/pick": "_post_pick",
        "/api/import/one": "_post_import",
        "/api/lrc": "_post_lrc",
        "/api/vocals": "_post_vocals",
        "/api/jobs": "_post_jobs",
        "/api/log": "_post_log",
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
        try:
            return self._do_GET()
        except Exception as e:
            diag.exception("http", e, method="GET", path=self.path)
            try:
                return self._json({"ok": False, "error": "内部错误"}, 500)
            except Exception:
                return None

    def _do_GET(self):
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
        if p.startswith("/api/jobs/"):
            return self._get_job(p[len("/api/jobs/"):])
        fn = self.GET.get(p)
        return getattr(self, fn)() if fn else self._send(404, "not found")

    # 每个写接口的必填字段（缺失直接 400，不让 service 里 KeyError/None 兜底）
    REQUIRED = {
        "/api/pl": ("action",),
        "/api/playlist": ("action",),
        "/api/line": ("idx", "line", "start", "reading"),
        "/api/rematch": ("idx",),
        "/api/pick": ("idx", "id"),
        "/api/import/one": ("paths",),
        "/api/lrc": ("idx",),
        "/api/vocals": ("idx",),
    }

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "请求不是合法 JSON"}, 400)
        fn = self.POST.get(p)
        if not fn:
            return self._send(404, "not found")
        missing = []
        for k in self.REQUIRED.get(p, ()):
            if k == "idx":
                if req.get("uid") in (None, "", [], {}) and req.get("idx") in (None, "", [], {}):
                    missing.append("uid/idx")
            elif req.get(k) in (None, "", [], {}):
                missing.append(k)
        if missing:
            return self._json({"ok": False, "error": "缺少参数：" + "/".join(missing)}, 400)
        if p != "/api/log" and req.get("generation") is not None:
            if str(req.get("generation")) != str(LIB.generation()):
                return self._json({"ok": False, "error": "曲库已更新，请重新加载"}, 409)
        try:
            return getattr(self, fn)(req)
        except Exception as e:
            diag.exception("http", e, method="POST", path=p)
            try:
                return self._json({"ok": False, "error": "内部错误"}, 500)
            except Exception:
                return None

    # ── GET ──────────────────────────────────────────
    def _get_playlists(self):
        d = SVC_PL.playlists_action({"action": "noop"})
        return self._json({"lists": d["lists"], "open": SVC_PL.playlists_open(),
                           "generation": LIB.generation()})

    def _get_library(self):
        rows = [{"idx": k, "uid": v.get("uid"), "title": v["title"],
                 "orig": v.get("orig") or v["title"], "artist": v["artist"],
                 "key": v["key"], "group": v.get("group", "")}
                for k, v in LIB.snapshot()]
        return self._json(rows)

    def _get_song(self, ref):
        try:
            return self._json(SVC_SONG.song_payload(ref))
        except Exception as e:
            return self._json({"error": str(e)}, 404)

    def _get_wave(self, ref):
        from ..core import waveform as WAVE
        from ..core import vocals as VOC
        q = urllib.parse.urlparse(self.path).query
        want = urllib.parse.parse_qs(q).get("src", ["mix"])[0]
        item = LIB.resolve(ref)
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

    def _get_vocals(self, ref):
        from ..core import vocals as VOC
        item = LIB.resolve(ref)
        if not item:
            return self._json({"error": "no such song"}, 404)
        return self._json(VOC.status(item["uid"]))

    def _post_vocals(self, req):
        from ..core import vocals as VOC
        item = LIB.resolve(req.get("uid") or req.get("idx"))
        if not item:
            return self._json({"ok": False, "error": "no such song"}, 404)
        return self._json(VOC.ensure(item["uid"], item["file"]))

    def _get_job(self, job_id):
        from ..core import jobs as JOBS
        job = JOBS.get(job_id)
        return self._json(job, 200 if job else 404)

    def _post_jobs(self, req):
        kind = req.get("kind")
        if not kind:
            return self._json({"ok": False, "error": "缺少任务类型"}, 400)
        try:
            job = SVC_JOBS.start(kind, req.get("uid") or req.get("idx"))
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)
        return self._json(job)

    _LOG_LOCK = threading.Lock()
    _LOG_TIMES: list[float] = []

    def _post_log(self, req):
        """前端未捕获错误写 app.log；限频，避免死循环刷日志。"""
        now = time.monotonic()
        with self._LOG_LOCK:
            self._LOG_TIMES[:] = [t for t in self._LOG_TIMES if now - t < 60]
            if len(self._LOG_TIMES) >= 30:
                return self._json({"ok": False, "skipped": True})
            self._LOG_TIMES.append(now)
        kind = str(req.get("kind") or "js")[:40]
        msg = str(req.get("message") or "")[:500]
        stack = str(req.get("stack") or "")[:4000]
        ctx = req.get("context") or {}
        try:
            ctx = {str(k)[:40]: ("" if v is None else str(v)[:200]) for k, v in list(ctx.items())[:20]}
        except Exception:
            ctx = {}
        diag.log("js", f"{kind} {msg}\n{stack}\n{json.dumps(ctx, ensure_ascii=False)}")
        return self._json({"ok": True})

    def _get_audio(self, ref):
        item = LIB.resolve(ref)
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

    def _post_line(self, req):
        return self._json(SVC_SONG.edit_line_action(req))

    def _post_rematch(self, req):
        return self._json(SVC_SONG.rematch(req.get("uid") or req.get("idx"), req.get("duration")))

    def _post_pick(self, req):
        r = SVC_SONG.pick(req.get("uid") or req.get("idx"), req.get("id"))
        return self._json(r, 200 if r.get("ok") else 400)

    def _post_lrc(self, req):
        return self._json(SVC_LRC.lrc_action(req))

