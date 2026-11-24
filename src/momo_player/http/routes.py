#!/usr/bin/env python3
"""HTTP 层：只做解析与转发，业务全在 service/。"""
from __future__ import annotations

import hmac
import json
import numbers
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

from ..core import diag
from ..core import library as LIB
from ..web import page
from ..service import jobs as SVC_JOBS
from ..service import lrc as SVC_LRC
from ..service import playlist as SVC_PL
from ..service import settings as SVC_SETTINGS
from ..service import song as SVC_SONG
from . import static as STATIC

TOKEN = secrets.token_urlsafe(32)
MAX_BODY = 2 * 1024 * 1024


class H(BaseHTTPRequestHandler):
    timeout = 15
    GET = {
        "/api/pl": "_get_playlists",
        "/api/library": "_get_library",
    }
    POST = {
        "/api/pl": "_post_pl",
        "/api/line": "_post_line",
        "/api/rematch": "_post_rematch",
        "/api/pick": "_post_pick",
        "/api/import/one": "_post_import",
        "/api/lrc": "_post_lrc",
        "/api/jobs": "_post_jobs",
        "/api/jobs/cancel_all": "_post_cancel_all_jobs",
        "/api/log": "_post_log",
        "/api/theme": "_post_theme",
    }

    # ── 基础 ─────────────────────────────────────────
    def log_message(self, *a):
        pass

    def _common_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy",
                         "camera=(), microphone=(), geolocation=()")

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self._common_headers()
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        # 所有 JSON 响应统一带 ok 字段；版本冲突映射 409，前端可单独处理。
        if isinstance(obj, dict):
            obj = dict(obj)
            if "ok" not in obj:
                obj["ok"] = False if obj.get("error") else True
            if code == 200 and obj.get("ok") is False and obj.get("conflict"):
                code = 409
        return self._send(code, json.dumps(obj, ensure_ascii=False))

    def _origin_host_ok(self) -> bool:
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{port}",
                                      f"http://localhost:{port}"):
            return False
        return True

    def _token_ok(self) -> bool:
        token = self.headers.get("X-Momo-Token") or ""
        return bool(token) and hmac.compare_digest(token, TOKEN)

    def _guard(self, protected: bool) -> bool:
        if not self._origin_host_ok():
            self._send(403, "forbidden")
            return False
        if protected and not self._token_ok():
            self._send(403, "forbidden")
            return False
        return True

    def do_OPTIONS(self):
        # 不提供 CORS；明确拒绝跨域预检。
        if not self._origin_host_ok():
            return self._send(403, "forbidden")
        return self._send(403, "forbidden")

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
        protected = p.startswith("/api/") or p.startswith("/audio/")
        if not self._guard(protected):
            return
        if p == "/":
            nonce = secrets.token_urlsafe(16)
            csp = ("default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                   "object-src 'none'; script-src 'self' 'unsafe-eval' 'nonce-" + nonce + "'; "
                   "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                   "media-src 'self' blob:; connect-src 'self'; font-src 'self'")
            return self._send(200, page(TOKEN, nonce), "text/html; charset=utf-8",
                              {"Content-Security-Policy": csp})
        if p.startswith("/static/"):
            it = STATIC.static_file(p)
            return self._send(200, it[0], it[1]) if it else self._send(404, "not found")
        if p.startswith("/api/song/"):
            return self._get_song(p[len("/api/song/"):])
        if p.startswith("/audio/"):
            return self._get_audio(p[len("/audio/"):])
        if p.startswith("/api/wave/"):
            return self._get_wave(p[len("/api/wave/"):])
        if p == "/api/jobs/active":
            return self._get_active_jobs()
        if p.startswith("/api/jobs/"):
            return self._get_job(p[len("/api/jobs/"):])
        fn = self.GET.get(p)
        return getattr(self, fn)() if fn else self._send(404, "not found")

    # 每个写接口的必填字段（缺失直接 400，不让 service 里 KeyError/None 兜底）
    REQUIRED = {
        "/api/pl": ("action",),
        "/api/line": ("uid", "line", "start", "reading"),
        "/api/rematch": ("uid",),
        "/api/pick": ("uid", "id"),
        "/api/import/one": ("paths",),
        "/api/lrc": ("uid",),
        "/api/theme": ("theme",),
    }

    def _is_int(self, v):
        return isinstance(v, int) and not isinstance(v, bool)

    def _is_num(self, v):
        return isinstance(v, numbers.Real) and not isinstance(v, bool)

    def _is_str_list(self, v):
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    def _is_lrc_lines(self, v):
        if not isinstance(v, list):
            return False
        for item in v:
            if not isinstance(item, dict):
                return False
            if "text" in item and not isinstance(item["text"], str):
                return False
            if "t" in item and item["t"] is not None and not self._is_num(item["t"]):
                return False
            if "trans" in item and item["trans"] is not None and not isinstance(item["trans"], str):
                return False
            if "tokens" in item and not isinstance(item["tokens"], list):
                return False
        return True

    def _is_lrc_rows(self, v):
        if not isinstance(v, list):
            return False
        for item in v:
            if not isinstance(item, dict):
                return False
            if "kind" in item and not isinstance(item["kind"], str):
                return False
            if "text" in item and not isinstance(item["text"], str):
                return False
            if "t" in item and item["t"] is not None and not self._is_num(item["t"]):
                return False
        return True

    def _is_trans_map(self, v):
        return isinstance(v, dict) and all(isinstance(x, str) for x in v.values())

    def _check_types(self, p, req):
        checks = {
            "/api/pl": {"action": str, "list": (str, type(None)),
                        "id": (str, type(None)), "name": (str, type(None)),
                        "ids": self._is_str_list, "uids": self._is_str_list,
                        "from": (str, type(None)), "to": (str, type(None)),
                        "uid": (str, type(None)), "paths": self._is_str_list},
            "/api/line": {"uid": str, "line": self._is_int,
                          "start": self._is_int, "reading": str,
                          "lid": (str, type(None)), "version": (str, type(None))},
            "/api/rematch": {"uid": str, "duration": self._is_num},
            "/api/pick": {"uid": str, "id": (str, int)},
            "/api/import/one": {"paths": self._is_str_list,
                                "list": (str, type(None)),
                                "with_lrc": bool},
            "/api/lrc": {"action": (str, type(None)), "uid": str,
                         "version": (str, type(None)), "lines": self._is_lrc_lines,
                         "rows": self._is_lrc_rows,
                         "translations": self._is_trans_map,
                         "compact_translations": self._is_trans_map,
                         "text": str},
            "/api/jobs": {"kind": str, "uid": (str, type(None))},
            "/api/jobs/cancel_all": {"kind": str},
            "/api/theme": {"theme": str},
            "/api/log": {"kind": (str, type(None)), "message": (str, type(None)),
                         "stack": (str, type(None)), "context": dict},
        }.get(p, {})
        for key, typ in checks.items():
            if key not in req:
                continue
            v = req[key]
            ok = False
            if isinstance(typ, tuple):
                ok = isinstance(v, typ)
            elif isinstance(typ, type):
                ok = isinstance(v, typ)
            else:
                ok = bool(typ(v))
            if not ok:
                return f"字段类型错误：{key}"
        if p == "/api/lrc":
            for key in ("lines", "rows"):
                if key in req and not (self._is_lrc_lines(req[key])
                                       if key == "lines" else self._is_lrc_rows(req[key])):
                    return f"字段类型错误：{key}"
        return None

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if not self._guard(True):
            return
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return self._json({"ok": False, "error": "Content-Type 必须是 application/json"}, 415)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"ok": False, "error": "Content-Length 无效"}, 400)
        if length < 0 or length > MAX_BODY:
            return self._json({"ok": False, "error": "请求体过大"}, 413)
        try:
            body = self.rfile.read(length)
        except (TimeoutError, OSError):
            return self._json({"ok": False, "error": "读取请求超时"}, 408)
        try:
            req = json.loads(body or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "请求不是合法 JSON"}, 400)
        if not isinstance(req, dict):
            return self._json({"ok": False, "error": "请求体必须是对象"}, 400)
        bad = self._check_types(p, req)
        if bad:
            return self._json({"ok": False, "error": bad}, 400)
        if p.startswith("/api/jobs/") and p.endswith("/cancel"):
            return self._post_cancel_job(p[len("/api/jobs/"):-len("/cancel")])
        fn = self.POST.get(p)
        if not fn:
            return self._send(404, "not found")
        missing = [k for k in self.REQUIRED.get(p, ())
                   if req.get(k) in (None, "", [], {})]
        if missing:
            return self._json({"ok": False, "error": "缺少参数：" + "/".join(missing)}, 400)
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
        return self._json({"lists": d["lists"], "open": SVC_PL.playlists_open()})

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

    def _get_job(self, job_id):
        from ..core import jobs as JOBS
        job = JOBS.get(job_id)
        return self._json(job, 200 if job else 404)

    def _get_active_jobs(self):
        return self._json({"ok": True, "jobs": SVC_JOBS.active_vocals()})

    def _post_cancel_job(self, job_id):
        job = SVC_JOBS.cancel_job(job_id)
        if not job:
            return self._json({"ok": False, "error": "任务不存在"}, 404)
        return self._json({"ok": True, "job": job})

    def _post_cancel_all_jobs(self, req):
        kind = str(req.get("kind") or "vocals")
        if kind != "vocals":
            return self._json({"ok": False, "error": "只支持取消人声任务"}, 400)
        return self._json({"ok": True, "jobs": SVC_JOBS.cancel_all_vocals()})

    def _post_jobs(self, req):
        kind = req.get("kind")
        if not kind:
            return self._json({"ok": False, "error": "缺少任务类型"}, 400)
        try:
            job = SVC_JOBS.start(kind, req.get("uid"))
        except SVC_JOBS.JobBusy as e:
            return self._json({"ok": False, "error": str(e)}, 429)
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
        self._common_headers()
        self.send_header("Content-Length", str(length))
        if crange:
            self.send_header("Content-Range", crange)
        self.end_headers()
        try:
            with open(item["file"], "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return                         # 前端 abort 音频请求：不是错误

    # ── POST ─────────────────────────────────────────
    def _post_pl(self, req):
        return self._json(SVC_PL.playlists_action(req))

    def _post_import(self, req):
        return self._json(SVC_PL.import_to_list(req))

    def _post_line(self, req):
        return self._json(SVC_SONG.edit_line_action(req))

    def _post_rematch(self, req):
        return self._json(SVC_SONG.rematch(req.get("uid"), req.get("duration")))

    def _post_pick(self, req):
        r = SVC_SONG.pick(req.get("uid"), req.get("id"))
        return self._json(r, 200 if r.get("ok") else 400)

    def _post_lrc(self, req):
        return self._json(SVC_LRC.lrc_action(req))

    def _post_theme(self, req):
        return self._json(SVC_SETTINGS.set_theme(req))

