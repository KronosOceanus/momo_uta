"""歌单接口：建/改名/删/清空/加/移除/排序/移动 + 导入。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from nihonco_player.core import playlists as PL   # noqa: E402
from nihonco_player.core import library as LIB       # noqa: E402
from nihonco_player.core.library import CACHE        # noqa: E402
from nihonco_player.http.server import make_server   # noqa: E402

FAKE = {"key": "k1", "uid": "u1", "file": "/tmp/a.mp3", "stem": "X - A", "orig": "A",
        "title": "A", "artist": "X", "group": "", "has_lyric": True}


def fake_item(uid, title="A"):
    return dict(FAKE, uid=uid, key=uid, file=f"/tmp/{uid}.mp3", stem=f"X - {title}", title=title)


class TestPlaylistsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._orig_file = PL.FILE
        PL.set_file(Path(cls.tmp.name) / "playlists.json")
        CACHE.clear()
        CACHE.update({str(i): fake_item(f"u{i}", f"曲{i}") for i in range(3)})
        cls._orig_scan = LIB.scan_library
        LIB.scan_library = lambda *a, **k: list(CACHE.values())
        cls.srv = make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        PL.set_file(cls._orig_file)
        LIB.scan_library = cls._orig_scan
        cls.tmp.cleanup()

    def post(self, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/pl",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    def get(self):
        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/pl").read())
        return d["lists"] if isinstance(d, dict) else d

    def test_default_exists_and_locked(self):
        pls = self.get()
        self.assertEqual(pls[0]["id"], "default")
        self.assertTrue(pls[0]["locked"])

    def test_create_and_add(self):
        self.post({"action": "list_create", "name": "新歌单"})
        lid = [g for g in self.get() if g["name"] == "新歌单"][0]["id"]
        self.post({"action": "entry_move", "from": "default", "to": lid, "uid": "u0"})
        g = [x for x in self.get() if x["id"] == lid][0]
        self.assertEqual([i["uid"] for i in g["items"]], ["u0"])

    def test_remove_from_list(self):
        self.post({"action": "entry_remove", "list": "default", "uid": "u1"})
        g = self.get()[0]
        self.assertNotIn("u1", [i["uid"] for i in g["items"]])

    def test_bulk_remove(self):
        self.post({"action": "list_create", "name": "批量删"})
        lid = [g for g in self.get() if g["name"] == "批量删"][0]["id"]
        PL.add(lid, ["u0", "u1", "u2"])
        self.post({"action": "entries_remove", "list": lid, "uids": ["u0", "u2"]})
        g = [x for x in self.get() if x["id"] == lid][0]
        self.assertEqual([i["uid"] for i in g["items"]], ["u1"])

    def test_clear(self):
        self.post({"action": "list_clear", "id": "default"})
        self.assertEqual(self.get()[0]["items"], [])

    def test_delete_removes_list(self):
        self.post({"action": "list_create", "name": "待删"})
        lid = [g for g in self.get() if g["name"] == "待删"][0]["id"]
        self.post({"action": "list_delete", "id": lid})
        self.assertNotIn(lid, [g["id"] for g in self.get()])

    def test_delete_default_refused(self):
        r = self.post({"action": "list_delete", "id": "default"})
        self.assertFalse(r["ok"])
        self.assertIn("默认", r["error"])

    def test_reorder_lists_keeps_default_first(self):
        self.post({"action": "list_create", "name": "A"})
        self.post({"action": "list_create", "name": "B"})
        ids = [g["id"] for g in self.get() if g["id"] != "default"]
        r = self.post({"action": "list_reorder", "ids": list(reversed(ids))})
        self.assertEqual(r["lists"][0]["id"], "default")
        self.assertEqual([g["id"] for g in r["lists"]][1:], list(reversed(ids)))


if __name__ == "__main__":
    unittest.main()


class TestImportToList(unittest.TestCase):
    def test_import_returns_library_count(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import fingerprint as FP
        from nihonco_player.core import importing as IMP
        from nihonco_player.core import library as LIB
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import playlist as SVC

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear()
            CACHE["0"] = {"key": "k", "uid": "fp1", "file": str(audio),
                          "stem": audio.stem, "orig": "曲", "title": "曲",
                          "artist": "歌手", "has_lyric": False, "group": ""}
            old = PL.FILE
            PL.set_file(root / "playlists.json")
            try:
                with patch.object(IMP, "import_paths",
                                  return_value={"added": [str(audio)], "pending": [],
                                                "overwritten": 0, "unpaired": 0}), \
                     patch.object(LIB, "save_import"), \
                     patch.object(LIB, "refresh", return_value=1), \
                     patch.object(FP, "fingerprint", return_value="fp1"):
                    res = SVC.import_to_list({"list": "default", "paths": [str(audio)]})
            finally:
                PL.set_file(old)
            self.assertTrue(res["ok"])
            self.assertEqual(res["library"], 1)
            self.assertEqual(res["imported"], 1)


class TestMatchAction(unittest.TestCase):
    def test_match_calls_lazy_match(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import playlist as SVC
        from nihonco_player.service import song as SONG

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            CACHE.clear()
            CACHE["0"] = {"key": "k", "uid": "fp1", "file": str(root / "a.mp3"),
                          "stem": "歌手 - 曲", "orig": "曲", "title": "曲",
                          "artist": "歌手", "has_lyric": False, "group": ""}
            old = PL.FILE
            PL.set_file(root / "playlists.json")
            try:
                with patch.object(SONG, "lazy_match") as lazy:
                    res = SVC.playlists_action({"action": "match", "idx": "0"})
            finally:
                PL.set_file(old)
            lazy.assert_called_once()
            self.assertTrue(res["ok"])
