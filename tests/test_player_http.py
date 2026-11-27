"""播放器接口层：起真服务（随机端口），打 6 个接口。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from momo_player.core import diag                  # noqa: E402
from momo_player.core import library as LIB        # noqa: E402
from momo_player.core import lyrics as LY         # noqa: E402
from momo_player.core import lrc_files as LRF     # noqa: E402
from momo_player.core import user_config as UC    # noqa: E402
from momo_yomi.config import PUI                  # noqa: E402
from momo_player.core.library import CACHE        # noqa: E402
from momo_player.http import routes as ROUTES      # noqa: E402
from momo_player.http.server import make_server   # noqa: E402

FAKE_LRC = "\n".join([
    "[00:00.00]作词 : X",
    "[00:10.00]あの日見渡した渚を",
    "[00:15.00]今も思い出すんだ",
    "[00:20.00]砂の上に刻んだ言葉",
])

CACHE_ITEM = {
    "key": "testkey000001", "uid": "uidtest000001", "file": "/tmp/fake.mp3", "stem": "テスト - テスト曲",
    "orig": "テスト曲", "title": "テスト曲", "artist": "テスト", "source": "netease",
    "lang": "ja", "suspect": False,
}


class TestPlayerHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._lyr_tmp = tempfile.TemporaryDirectory()
        cls._lyr_patch = patch.object(LRF, "LYRICS", Path(cls._lyr_tmp.name) / "lyrics")
        cls._lyr_patch.start()
        CACHE.clear()
        CACHE["0"] = CACHE_ITEM
        LIB.BY_UID[CACHE_ITEM["uid"]] = CACHE_ITEM
        # 让 song_payload 拿到固定歌词，不走网络
        cls._orig_get = LY.get_lrc
        LY.get_lrc = lambda *a, **k: {"lrc": FAKE_LRC, "tlyric": "", "name": "テスト曲",
                                        "artist": "テスト", "lang": "ja"}
        cls.srv = make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls._lyr_patch.stop()
        cls._lyr_tmp.cleanup()
        LY.get_lrc = cls._orig_get

    def setUp(self):
        # 每个用例重新放一份固定 CACHE，避免上一条写歌词/refresh 污染下一条。
        CACHE.clear()
        CACHE["0"] = dict(CACHE_ITEM)
        LIB.BY_UID.clear()
        LIB.BY_UID[CACHE_ITEM["uid"]] = CACHE["0"]

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def auth_headers(self, extra=None):
        h = dict(extra or {})
        h["X-Momo-Token"] = ROUTES.TOKEN
        return h

    def get(self, path):
        return urllib.request.urlopen(urllib.request.Request(
            self.url(path), headers=self.auth_headers()))

    def post(self, path, body):
        req = urllib.request.Request(self.url(path), data=json.dumps(body).encode(),
                                     headers=self.auth_headers(
                                         {"Content-Type": "application/json"}))
        return urllib.request.urlopen(req)

    def test_missing_params_returns_400(self):
        req = urllib.request.Request(self.url("/api/line"), data=b"{}",
                                     headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        body = json.loads(cm.exception.read())
        self.assertIn("缺少参数", body["error"])

    def test_page(self):
        html = self.get("/").read().decode()
        self.assertIn("momo uta", html)
        self.assertIn("resetall", html)

    def test_page_does_not_leak_token_or_paths_and_has_no_cors(self):
        r = self.get("/")
        html = r.read().decode()
        self.assertNotIn(ROUTES.TOKEN, html)
        self.assertNotIn("music_dirs", html)
        self.assertIn("URLSearchParams", html)
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        csp = r.headers.get("Content-Security-Policy") or ""
        self.assertIn("script-src 'self' 'unsafe-eval' 'nonce-", csp)
        nonce = csp.split("'nonce-", 1)[1].split("'", 1)[0]
        self.assertIn(f'nonce="{nonce}"', html)

    def test_api_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.url("/api/library"))
        self.assertEqual(cm.exception.code, 403)

    def test_wrong_origin_rejected(self):
        req = urllib.request.Request(
            self.url("/api/library"),
            headers={**self.auth_headers(), "Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_wrong_field_type_returns_400(self):
        req = urllib.request.Request(
            self.url("/api/line"),
            data=json.dumps({"uid": CACHE_ITEM["uid"], "line": "x",
                             "start": 0, "reading": "か"}).encode(),
            headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("line", json.loads(cm.exception.read())["error"])

    def test_wrong_string_field_type_returns_400(self):
        req = urllib.request.Request(
            self.url("/api/line"),
            data=json.dumps({"uid": CACHE_ITEM["uid"], "line": 1,
                             "start": 0, "reading": 3}).encode(),
            headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("reading", json.loads(cm.exception.read())["error"])

    def test_non_object_body_returns_400(self):
        req = urllib.request.Request(
            self.url("/api/line"), data=b"[]",
            headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)

    def test_post_requires_json_content_type(self):
        req = urllib.request.Request(
            self.url("/api/line"), data=b"{}",
            headers={**self.auth_headers(), "Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 415)

    def test_options_has_no_cors(self):
        req = urllib.request.Request(self.url("/api/library"), method="OPTIONS")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)
        self.assertIsNone(cm.exception.headers.get("Access-Control-Allow-Origin"))

    def test_non_ascii_token_is_rejected_without_disconnect(self):
        req = urllib.request.Request(self.url("/api/library"),
                                     headers={"X-Momo-Token": "é"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_http_concurrency_limit_returns_503(self):
        old = ROUTES._SLOTS
        ROUTES._SLOTS = threading.BoundedSemaphore(1)
        ROUTES._SLOTS.acquire()
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(self.url("/"))
            self.assertEqual(cm.exception.code, 503)
        finally:
            ROUTES._SLOTS.release()
            ROUTES._SLOTS = old


    def test_audio_response_has_security_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "fake.mp3"; audio.write_bytes(b"0123456789")
            CACHE["0"]["file"] = str(audio)
            r = self.get("/audio/" + CACHE_ITEM["uid"])
            self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.headers.get("Cache-Control"), "no-store")
            self.assertEqual(r.headers.get("Accept-Ranges"), "bytes")

    def test_query_token_is_not_accepted(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.url("/api/library?token=" + ROUTES.TOKEN))
        self.assertEqual(cm.exception.code, 403)

    def test_forbidden_is_json(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.url("/api/library"))
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(json.loads(cm.exception.read())["error"], "forbidden")

    def test_head_page_has_headers_and_no_body(self):
        req = urllib.request.Request(self.url("/"), method="HEAD")
        r = urllib.request.urlopen(req)
        self.assertEqual(r.read(), b"")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertGreater(int(r.headers.get("Content-Length", "0")), 0)

    def test_head_audio_has_headers_and_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "fake.mp3"; audio.write_bytes(b"0123456789")
            CACHE["0"]["file"] = str(audio)
            req = urllib.request.Request(
                self.url("/audio/" + CACHE_ITEM["uid"]), method="HEAD",
                headers=self.auth_headers())
            r = urllib.request.urlopen(req)
            self.assertEqual(r.read(), b"")
            self.assertEqual(r.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(r.headers.get("Content-Length"), "10")

    def test_song_error_does_not_leak_internal_detail(self):
        from momo_player.service import song as SVC_SONG
        with patch.object(SVC_SONG, "song_payload",
                          side_effect=RuntimeError("/secret/path")):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get("/api/song/" + CACHE_ITEM["uid"])
        body = cm.exception.read().decode()
        self.assertEqual(cm.exception.code, 404)
        self.assertNotIn("/secret/path", body)
        self.assertIn("歌曲不可用", body)

    def test_library(self):
        rows = json.loads(self.get("/api/library").read())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["orig"], "テスト曲")

    def test_song_payload(self):
        d = json.loads(self.get("/api/song/" + CACHE_ITEM["uid"]).read())
        self.assertGreaterEqual(len(d["lines"]), 3)
        self.assertIs(d.get("ok"), True)
        self.assertTrue(any(l["ruby"] for l in d["lines"]))
        self.assertIn("rmH", d["lines"][1])
        self.assertEqual(d["idx"], "0")
        self.assertIsInstance(d["idx"], str)
        self.assertFalse(d["pending"])
        self.assertEqual([c["text"] for c in d["credits"]], ["作词 : X"])
        self.assertIn("vocals", d)

    def test_song_idx_is_not_accepted(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/song/0")
        self.assertEqual(cm.exception.code, 404)

    def test_song_payload_by_uid(self):
        d = json.loads(self.get("/api/song/" + CACHE_ITEM["uid"]).read())
        self.assertEqual(d["uid"], CACHE_ITEM["uid"])
        self.assertEqual(d["audio"], "/audio/" + CACHE_ITEM["uid"])
        self.assertEqual(d["idx"], "0")
        self.assertGreaterEqual(len(d["lines"]), 3)

    def test_edit_line(self):
        """改一处读音：返回新 ruby 且罗马音跟着变。"""
        li, start = 1, 2                      # 第 2 行的「日」
        d = json.loads(self.post("/api/line", {"uid": CACHE_ITEM["uid"], "line": li,
                                               "start": start, "reading": "か"}).read())
        self.assertEqual(d["line"], li)
        self.assertIn("<rt>か</rt>", d["ruby"])
        self.assertIn("ka", d["rm"])
        self.assertTrue(d.get("version"))

    def test_lrc_version_conflict_is_409(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"):
                path = LRF.store_path(CACHE_ITEM["file"], CACHE_ITEM["uid"],
                                      CACHE_ITEM["title"], CACHE_ITEM["artist"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[00:01.00]君の名前\n", encoding="utf-8")
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self.post("/api/lrc", {
                        "action": "save", "uid": CACHE_ITEM["uid"],
                        "version": "stale",
                        "lines": [{"t": 1.0, "text": "君の名前"}]})
                self.assertEqual(cm.exception.code, 409)
                err = json.loads(cm.exception.read())
                self.assertFalse(err["ok"])
                self.assertTrue(err.get("conflict"))

    def test_theme_endpoint_persists_and_page_uses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            old = (UC.FILE, UC.LOCK, PUI.get("theme"))
            UC.FILE, UC.LOCK = p, p.with_suffix(".lock")
            try:
                d = json.loads(self.post("/api/theme", {"theme": "light"}).read())
                self.assertTrue(d["ok"])
                self.assertEqual(d["theme"], "light")
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"player": {"ui": {"theme": "light"}}})
                page = self.get("/").read().decode()
                self.assertIn('data-theme="light"', page)
            finally:
                UC.FILE, UC.LOCK = old[0], old[1]
                PUI["theme"] = old[2]

    def test_play_mode_endpoint_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            old = (UC.FILE, UC.LOCK, PUI.get("play_mode"))
            UC.FILE, UC.LOCK = p, p.with_suffix(".lock")
            try:
                d = json.loads(self.post("/api/play_mode", {"mode": "shuffle"}).read())
                self.assertTrue(d["ok"])
                self.assertEqual(d["mode"], "shuffle")
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"player": {"ui": {"play_mode": "shuffle"}}})
            finally:
                UC.FILE, UC.LOCK = old[0], old[1]
                PUI["play_mode"] = old[2]

    def test_client_log_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            with patch.object(diag, "LOG", log):
                d = json.loads(self.post("/api/log", {
                    "kind": "js_error", "message": "boom", "stack": "at x",
                    "context": {"phase": "ready"}}).read())
            self.assertTrue(d["ok"])
            text = log.read_text(encoding="utf-8")
            self.assertIn("boom", text)
            self.assertIn("js_error", text)
    def test_client_log_strips_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            with patch.object(diag, "LOG", log):
                self.post("/api/log", {
                    "kind": "js", "message": "boom\n[py 00:00:00] [http] fake",
                    "stack": "a\nb", "context": {"x": "1\n2"}}).read()
            text = log.read_text(encoding="utf-8")
        self.assertNotIn("\n[py 00:00:00] [http] fake", text)


    def test_unexpected_handler_exception_returns_json_500(self):
        def boom(self, req):
            raise RuntimeError("handler boom")
        old_route = ROUTES.H.POST.get("/api/__test_boom")
        old_method = getattr(ROUTES.H, "_test_boom", None)
        ROUTES.H.POST["/api/__test_boom"] = "_test_boom"
        ROUTES.H._test_boom = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / "app.log"
                with patch.object(diag, "LOG", log):
                    req = urllib.request.Request(self.url("/api/__test_boom"), data=b"{}",
                                                 headers=self.auth_headers({"Content-Type": "application/json"}))
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req)
                self.assertEqual(cm.exception.code, 500)
                body = json.loads(cm.exception.read())
                self.assertIn("内部错误", body["error"])
                text = log.read_text(encoding="utf-8")
                self.assertIn("handler boom", text)
                self.assertIn("http", text)
        finally:
            ROUTES.H.POST.pop("/api/__test_boom", None)
            if old_route is not None:
                ROUTES.H.POST["/api/__test_boom"] = old_route
            if old_method is None:
                delattr(ROUTES.H, "_test_boom")
            else:
                ROUTES.H._test_boom = old_method

    def test_unexpected_get_exception_returns_json_500(self):
        def boom(self):
            raise RuntimeError("get boom")
        old_route = ROUTES.H.GET.get("/api/__test_boom_get")
        old_method = getattr(ROUTES.H, "_test_boom_get", None)
        ROUTES.H.GET["/api/__test_boom_get"] = "_test_boom_get"
        ROUTES.H._test_boom_get = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / "app.log"
                with patch.object(diag, "LOG", log):
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        self.get("/api/__test_boom_get")
                self.assertEqual(cm.exception.code, 500)
                self.assertIn("内部错误", json.loads(cm.exception.read())["error"])
                self.assertIn("get boom", log.read_text(encoding="utf-8"))
        finally:
            ROUTES.H.GET.pop("/api/__test_boom_get", None)
            if old_route is not None:
                ROUTES.H.GET["/api/__test_boom_get"] = old_route
            if old_method is None:
                delattr(ROUTES.H, "_test_boom_get")
            else:
                ROUTES.H._test_boom_get = old_method

    def test_idx_write_rejected(self):
        body = {"idx": "0", "line": 1, "start": 2, "reading": "か"}
        req = urllib.request.Request(self.url("/api/line"), data=json.dumps(body).encode(),
                                     headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)

    def test_bad_json(self):
        req = urllib.request.Request(self.url("/api/line"), data=b"{oops",
                                     headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_soundtouch_info(self):
        payload = {"uid": "u", "speed": 0.8, "url": "/audio/u?st=0.80",
                   "duration": 1.0, "bytes": 2}
        with patch.object(ROUTES.SVC_ST, "info", return_value=payload) as info:
            r = self.post("/api/soundtouch", {"uid": "u", "speed": 0.8})
            d = json.loads(r.read())
        self.assertTrue(d["ok"])
        self.assertEqual(d["url"], payload["url"])
        info.assert_called_once_with("u", 0.8)

    def test_soundtouch_info_with_key(self):
        payload = {"uid": "u", "speed": 0.8, "key": 2,
                   "url": "/audio/u?st=0.80&key=2", "duration": 1.0, "bytes": 2}
        with patch.object(ROUTES.SVC_ST, "info", return_value=payload) as info:
            d = json.loads(self.post("/api/soundtouch",
                                     {"uid": "u", "speed": 0.8, "key": 2}).read())
        self.assertTrue(d["ok"])
        self.assertEqual(d["url"], payload["url"])
        info.assert_called_once_with("u", 0.8, 2)

    def test_soundtouch_audio_uses_key_cache(self):
        with patch.object(ROUTES.SVC_ST, "cached_path", return_value=None) as cached:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(f"/audio/{CACHE_ITEM['uid']}?st=0.80&key=2")
        self.assertEqual(cm.exception.code, 404)
        cached.assert_called_once_with(CACHE_ITEM["uid"], 0.8, 2)

    def test_soundtouch_cancel(self):
        with patch.object(ROUTES.SVC_ST, "cancel") as cancel:
            r = self.post("/api/soundtouch/cancel", {"uid": "u"})
            d = json.loads(r.read())
        self.assertTrue(d["ok"])
        cancel.assert_called_once_with("u")



    def test_soundtouch_cancel_requires_uid(self):
        req = urllib.request.Request(self.url("/api/soundtouch/cancel"), data=b"{}",
                                     headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)



    def test_soundtouch_audio_does_not_generate_on_get(self):
        with patch.object(ROUTES.SVC_ST, "process") as process, \
             patch.object(ROUTES.SVC_ST, "cached_path", return_value=None):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(f"/audio/{CACHE_ITEM['uid']}?st=0.80")
        self.assertEqual(cm.exception.code, 404)
        process.assert_not_called()



    def test_soundtouch_audio_cache_hit_range(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            path = Path(fh.name)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"\x00" * 200)
        try:
            with patch.object(ROUTES.SVC_ST, "cached_path", return_value=path):
                req = urllib.request.Request(
                    self.url(f"/audio/{CACHE_ITEM['uid']}?st=0.80"),
                    headers={**self.auth_headers(), "Range": "bytes=0-9"})
                r = urllib.request.urlopen(req)
                self.assertEqual(r.status, 206)
                self.assertEqual(len(r.read()), 10)
                self.assertIn("bytes 0-9/", r.headers.get("Content-Range", ""))
        finally:
            path.unlink(missing_ok=True)


    def test_audio_open_failure_is_404_not_stream_500(self):
        with patch("builtins.open", side_effect=OSError("gone")):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get("/audio/" + CACHE_ITEM["uid"])
        self.assertEqual(cm.exception.code, 404)

    def test_soundtouch_error_has_code(self):
        req = urllib.request.Request(
            self.url("/api/soundtouch"), data=json.dumps({"uid": "uidtest000001",
                                                          "speed": 99}).encode(),
            headers=self.auth_headers({"Content-Type": "application/json"}))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        body = json.loads(cm.exception.read())
        self.assertEqual(body["error_code"], "invalid_speed")


class TestSongPayloadVocals(unittest.TestCase):
    def test_payload_carries_each_vocals_state(self):
        from unittest.mock import patch
        from momo_player.service import song as SVC
        item = {"uid": "u0", "file": "/tmp/x.mp3", "key": "k", "title": "x",
                "artist": "", "stem": "x - x"}
        for state in ("none", "queued", "running", "done", "failed"):
            with patch.object(SVC.VOC, "status",
                              return_value={"state": state, "has_vocals": state == "done"}), \
                 patch.object(SVC.LY, "audio_duration", return_value=60):
                base = SVC._payload_base(item, "0", "u0", {})
            self.assertEqual(base["vocals"]["state"], state)


class TestLrcNestedTypes(unittest.TestCase):
    def test_bad_lrc_lines(self):
        # reuse an isolated server through the existing fixture-style setup
        from tests.test_player_http import TestPlayerHttp
        case = TestPlayerHttp("test_library")
        case.setUpClass()
        try:
            case.setUp()
            body = {"action": "save", "uid": CACHE_ITEM["uid"], "lines": ["x"]}
            req = urllib.request.Request(
                case.url("/api/lrc"), data=json.dumps(body).encode(),
                headers=case.auth_headers({"Content-Type": "application/json"}))
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 400)
        finally:
            case.tearDownClass()


if __name__ == "__main__":
    unittest.main()
