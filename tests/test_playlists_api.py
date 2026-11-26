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
from momo_player.core import playlists as PL   # noqa: E402
from momo_player.core import library as LIB       # noqa: E402
from momo_player.core.library import CACHE        # noqa: E402
from momo_player.http import routes as ROUTES      # noqa: E402
from momo_player.http.server import make_server   # noqa: E402

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

    def _headers(self):
        return {"X-Momo-Token": ROUTES.TOKEN}

    def post(self, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/pl",
                                     data=json.dumps(body).encode(),
                                     headers={**self._headers(),
                                              "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    def get(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/pl",
                                     headers=self._headers())
        d = json.loads(urllib.request.urlopen(req).read())
        return d["lists"] if isinstance(d, dict) else d

    def test_default_exists_and_locked(self):
        pls = self.get()
        self.assertEqual(pls[0]["id"], "default")
        self.assertTrue(pls[0]["locked"])

    def test_create_and_add(self):
        self.post({"action": "list_create", "name": "新歌单"})
        lid = [g for g in self.get() if g["name"] == "新歌单"][0]["id"]
        PL.add("default", ["u0"])
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
        from momo_player.core import fingerprint as FP
        from momo_player.core import importing as IMP
        from momo_player.core import library as LIB
        from momo_player.core.library import CACHE, BY_UID
        from momo_player.service import playlist as SVC

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear(); BY_UID.clear()
            CACHE["0"] = {"key": "k", "uid": "fp1", "file": str(audio),
                          "stem": audio.stem, "orig": "曲", "title": "曲",
                          "artist": "歌手", "has_lyric": False, "group": ""}
            BY_UID["fp1"] = CACHE["0"]
            old = PL.FILE
            PL.set_file(root / "playlists.json")
            try:
                with patch.object(IMP, "import_paths",
                                  return_value={"added": [str(audio)], "pending": [],
                                                "overwritten": 0, "unpaired": 0}) as imp, \
                     patch.object(LIB, "save_import"), \
                     patch.object(LIB, "refresh", return_value=1), \
                     patch.object(FP, "fingerprint", return_value="fp1"):
                    res = SVC.import_to_list({"list": "default", "paths": [str(audio)],
                                              "versions": {str(audio): "v1"}})
                self.assertEqual(imp.call_args.kwargs["versions"], {str(audio): "v1"})
            finally:
                PL.set_file(old)
            self.assertTrue(res["ok"])
            self.assertEqual(res["library"], 1)
            self.assertEqual(res["imported"], 1)


class TestUnknownUid(unittest.TestCase):
    def test_song_action_reports_missing_uid(self):
        import tempfile
        from pathlib import Path
        from momo_player.core import library as LIB
        from momo_player.core.library import CACHE
        from momo_player.service import playlist as SVC
        with tempfile.TemporaryDirectory() as tmp:
            CACHE.clear(); LIB.BY_UID.clear()
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                for action in ("edit_clear", "ui_offset", "match"):
                    r = SVC.playlists_action({"action": action, "uid": "missing"})
                    self.assertFalse(r["ok"], action)
                    self.assertIn("不可用", r["error"])
            finally:
                PL.set_file(old)


class TestMatchAction(unittest.TestCase):
    def test_match_calls_lazy_match(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import library as LIB
        from momo_player.core.library import CACHE
        from momo_player.service import playlist as SVC
        from momo_player.service import song as SONG

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            CACHE.clear()
            it = {"key": "k", "uid": "fp1", "file": str(root / "a.mp3"),
                  "stem": "歌手 - 曲", "orig": "曲", "title": "曲",
                  "artist": "歌手", "has_lyric": False, "group": ""}
            CACHE["0"] = it
            LIB.BY_UID["fp1"] = it
            old = PL.FILE
            PL.set_file(root / "playlists.json")
            try:
                with patch.object(SONG, "lazy_match") as lazy:
                    res = SVC.playlists_action({"action": "match", "uid": "fp1"})
            finally:
                PL.set_file(old)
            lazy.assert_called_once()
            self.assertTrue(res["ok"])


class TestPlaylistBadData(unittest.TestCase):
    def test_bad_entries_are_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            p = Path(tmp) / "playlists.json"
            p.write_text(json.dumps({
                "lists": [None, 3, {"id": 1, "name": "bad"},
                          {"id": "x", "name": "X"},
                          {"id": "x", "name": "dup"}],
                "members": {"default": "not-a-list",
                            "x": ["u1", None, 3, "u1", "u2"]},
                "list_order": "bad", "open": [1, "x"],
            }), encoding="utf-8")
            PL.set_file(p)
            try:
                d = PL.load()
            finally:
                PL.set_file(old)
            self.assertEqual([x["id"] for x in d["lists"]], ["default", "x"])
            self.assertEqual(d["members"]["default"], [])
            self.assertEqual(d["members"]["x"], ["u1", "u2"])
            self.assertEqual(d["list_order"], [])
            self.assertEqual(d["open"], ["x"])

    def test_non_dict_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            p = Path(tmp) / "playlists.json"
            p.write_text("[]", encoding="utf-8")
            PL.set_file(p)
            try:
                d = PL.load()
            finally:
                PL.set_file(old)
            self.assertEqual([x["id"] for x in d["lists"]], ["default"])
            self.assertEqual(d["members"], {"default": []})


class TestImportConsistency(unittest.TestCase):
    def test_missing_list_is_rejected_before_import(self):
        from unittest.mock import patch
        from momo_player.service import playlist as SVC
        from momo_player.core import importing as IMP
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                with patch.object(IMP, "import_paths") as imp:
                    r = SVC.import_to_list({"list": "missing", "paths": ["/tmp/x.mp3"]})
                self.assertFalse(r["ok"])
                self.assertIn("歌单不存在", r["error"])
                imp.assert_not_called()
            finally:
                PL.set_file(old)

    def test_clear_unknown_list_does_not_create_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                PL.clear("missing")
                self.assertNotIn("missing", PL.load()["members"])
            finally:
                PL.set_file(old)

    def test_move_to_unknown_list_does_not_create_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                PL.add("default", ["u1"])
                PL.move_many("default", "missing", ["u1"])
                self.assertNotIn("missing", PL.load()["members"])
                self.assertEqual(PL.load()["members"]["default"], ["u1"])
            finally:
                PL.set_file(old)

    def test_add_to_unknown_list_does_not_create_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                self.assertEqual(PL.add("missing", ["u1"]), 0)
                self.assertNotIn("missing", PL.load()["members"])
            finally:
                PL.set_file(old)


class TestImportPlaylistWriteFailure(unittest.TestCase):
    def test_playlist_add_error_is_returned(self):
        from unittest.mock import patch
        from momo_player.service import playlist as SVC
        from momo_player.core import importing as IMP
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                with patch.object(IMP, "import_paths",
                                  return_value={"added": [], "pending": [], "failed": []}), \
                     patch.object(SVC.PL, "add", side_effect=OSError("disk full")):
                    r = SVC.import_to_list({"list": "default", "paths": ["/tmp/x.mp3"]})
                self.assertFalse(r["ok"])
                self.assertIn("加入歌单失败", r["error"])
            finally:
                PL.set_file(old)


class TestMoveSource(unittest.TestCase):
    def test_move_missing_source_member_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                lid = PL.create("目标")
                PL.add("default", ["u1"])
                PL.move("default", lid, "u2")
                d = PL.load()
                self.assertEqual(d["members"]["default"], ["u1"])
                self.assertEqual(d["members"][lid], [])
            finally:
                PL.set_file(old)


class TestRemoveUnknownList(unittest.TestCase):
    def test_remove_many_unknown_list_does_not_create_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                PL.remove_many("missing", ["u1"])
                self.assertNotIn("missing", PL.load()["members"])
            finally:
                PL.set_file(old)


class TestImportListDisappears(unittest.TestCase):
    def test_list_gone_after_add_returns_error(self):
        from unittest.mock import patch
        from momo_player.service import playlist as SVC
        from momo_player.core import importing as IMP
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                calls = []
                def exists(lid):
                    calls.append(lid)
                    return len(calls) == 1
                with patch.object(IMP, "import_paths",
                                  return_value={"added": [], "pending": [], "failed": []}), \
                     patch.object(SVC.PL, "exists", side_effect=exists), \
                     patch.object(SVC.PL, "add", return_value=0):
                    r = SVC.import_to_list({"list": "default", "paths": ["/tmp/x.mp3"]})
                self.assertFalse(r["ok"])
                self.assertIn("歌单已不存在", r["error"])
            finally:
                PL.set_file(old)


class TestImportPathCap(unittest.TestCase):
    def test_too_many_paths_are_rejected_before_import(self):
        from unittest.mock import patch
        from momo_player.service import playlist as SVC
        from momo_player.core import importing as IMP
        with tempfile.TemporaryDirectory() as tmp:
            old = PL.FILE
            PL.set_file(Path(tmp) / "playlists.json")
            try:
                paths = [f"/tmp/momo-{i}.mp3" for i in range(IMP.MAX_IMPORT_PATHS + 1)]
                with patch.object(IMP, "import_paths") as imp:
                    r = SVC.import_to_list({"list": "default", "paths": paths})
                self.assertFalse(r["ok"])
                self.assertIn("最多导入", r["error"])
                imp.assert_not_called()
            finally:
                PL.set_file(old)
