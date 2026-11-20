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
from nihonco_player.core import lyrics as LY         # noqa: E402
from nihonco_player.core import lrc_files as LRF     # noqa: E402
from nihonco_player.core.library import CACHE        # noqa: E402
from nihonco_player.http.server import make_server   # noqa: E402

FAKE_LRC = "\n".join([
    "[00:00.00]作词 : X",
    "[00:10.00]あの日見渡した渚を",
    "[00:15.00]今も思い出すんだ",
    "[00:20.00]砂の上に刻んだ言葉",
])

CACHE_ITEM = {
    "key": "testkey000001", "file": "/tmp/fake.mp3", "stem": "テスト - テスト曲",
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

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, path, body):
        req = urllib.request.Request(self.url(path), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req)

    def test_missing_params_returns_400(self):
        req = urllib.request.Request(self.url("/api/line"), data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        body = json.loads(cm.exception.read())
        self.assertIn("缺少参数", body["error"])

    def test_page(self):
        html = urllib.request.urlopen(self.url("/")).read().decode()
        self.assertIn("nihonco uta", html)
        self.assertIn("resetall", html)

    def test_library(self):
        rows = json.loads(urllib.request.urlopen(self.url("/api/library")).read())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["orig"], "テスト曲")

    def test_song_payload(self):
        d = json.loads(urllib.request.urlopen(self.url("/api/song/0")).read())
        self.assertGreaterEqual(len(d["lines"]), 3)
        self.assertTrue(any(l["ruby"] for l in d["lines"]))
        self.assertIn("rmH", d["lines"][1])

    def test_edit_line(self):
        """改一处读音：返回新 ruby 且罗马音跟着变。"""
        song = json.loads(urllib.request.urlopen(self.url("/api/song/0")).read())
        li, start = 1, 2                      # 第 2 行的「日」
        d = json.loads(self.post("/api/line", {"idx": "0", "line": li, "start": start,
                                               "reading": "か"}).read())
        self.assertEqual(d["line"], li)
        self.assertIn("<rt>か</rt>", d["ruby"])
        self.assertIn("ka", d["rm"])

    def test_bad_json(self):
        req = urllib.request.Request(self.url("/api/line"), data=b"{oops",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
