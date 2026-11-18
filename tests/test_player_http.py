"""播放器接口层：起真服务（随机端口），打 6 个接口。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from nihonco_player import edits as ED      # noqa: E402
from nihonco_player import server as S  # noqa: E402

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
        S.CACHE.clear()
        S.CACHE["0"] = CACHE_ITEM
        # 让 song_payload 拿到固定歌词，不走网络
        cls._orig_get = S.LY.get_lrc
        S.LY.get_lrc = lambda *a, **k: {"lrc": FAKE_LRC, "tlyric": "", "name": "テスト曲",
                                        "artist": "テスト", "lang": "ja"}
        cls.tmp = tempfile.TemporaryDirectory()
        S.LIB.TAGS = Path(cls.tmp.name) / "tags.json"
        cls._orig_readings = ED.FILE
        ED.set_file(Path(cls.tmp.name) / "readings.json")
        cls.srv = S.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        S.LY.get_lrc = cls._orig_get
        ED.set_file(cls._orig_readings)
        cls.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, path, body):
        req = urllib.request.Request(self.url(path), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req)

    def test_page(self):
        html = urllib.request.urlopen(self.url("/")).read().decode()
        self.assertIn("逐句练习", html)
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

    def test_tag_roundtrip(self):
        d = json.loads(self.post("/api/tag", {"action": "tag", "key": "k1", "tag": "inst"}).read())
        self.assertEqual(d["tags"], ["inst"])
        d2 = json.loads(self.post("/api/tag", {"action": "tag", "key": "k1", "tag": "inst"}).read())
        self.assertEqual(d2["tags"], [])

    def test_bad_json(self):
        req = urllib.request.Request(self.url("/api/line"), data=b"{oops",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
