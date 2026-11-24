"""播放器接口层：起真服务（随机端口），打 6 个接口。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
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

    def test_page_injects_token_and_has_no_cors(self):
        r = self.get("/")
        html = r.read().decode()
        self.assertIn(ROUTES.TOKEN, html)
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

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


if __name__ == "__main__":
    unittest.main()
