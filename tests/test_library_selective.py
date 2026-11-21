"""启动按需加载：只取歌单成员 + imports，索引缺失才全量兜底。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import fingerprint as FP
from nihonco_player.core import library as LIB
from nihonco_player.core.library import CACHE


class TestSelectiveLibrary(unittest.TestCase):
    def setUp(self):
        self.old = dict(CACHE)
        CACHE.clear()

    def tearDown(self):
        CACHE.clear()
        CACHE.update(self.old)

    def test_only_playlist_uids_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "X - A.mp3"; a.touch()
            b = root / "X - B.mp3"; b.touch()
            with patch.object(LIB, "load_imports", return_value=[]), \
                 patch.object(FP, "paths_for_uids", return_value={"u1": [str(a)]}), \
                 patch.object(FP, "fingerprint", side_effect=lambda p: "u1" if str(p) == str(a) else "u2"), \
                 patch.object(LIB, "scan_library", side_effect=AssertionError("不该全量扫描")):
                # all_uids 通过临时 playlists 文件提供
                from nihonco_player.core import playlists as PL
                old = PL.FILE
                PL.set_file(root / "playlists.json")
                try:
                    PL.add("default", ["u1"])
                    lib = LIB.load_for_playlists()
                finally:
                    PL.set_file(old)
            self.assertEqual([x["file"] for x in lib], [str(a)])

    def test_imports_are_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "X - A.mp3"; a.touch()
            b = root / "X - B.mp3"; b.touch()
            with patch.object(LIB, "load_imports", return_value=[{"audio": str(b)}]), \
                 patch.object(FP, "paths_for_uids", return_value={"u1": [str(a)]}), \
                 patch.object(FP, "fingerprint", side_effect=lambda p: "u1" if str(p) == str(a) else "u2"), \
                 patch.object(LIB, "scan_library", side_effect=AssertionError("不该全量扫描")):
                from nihonco_player.core import playlists as PL
                old = PL.FILE
                PL.set_file(root / "playlists.json")
                try:
                    PL.add("default", ["u1"])
                    lib = LIB.load_for_playlists()
                finally:
                    PL.set_file(old)
            self.assertEqual({x["file"] for x in lib}, {str(a), str(b)})

    def test_unresolved_uid_falls_back_to_full_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "X - A.mp3"; a.touch()
            with patch.object(LIB, "load_imports", return_value=[]), \
                 patch.object(FP, "paths_for_uids", return_value={}), \
                 patch.object(LIB, "scan_library", return_value=[{"uid": "u1", "file": str(a)}]) as scan:
                from nihonco_player.core import playlists as PL
                old = PL.FILE
                PL.set_file(root / "playlists.json")
                try:
                    PL.add("default", ["u1"])
                    lib = LIB.load_for_playlists()
                finally:
                    PL.set_file(old)
            scan.assert_called_once()
            self.assertEqual(lib[0]["uid"], "u1")


if __name__ == "__main__":
    unittest.main()
