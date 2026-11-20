"""CACHE 刷新：单条替换不动其它条目，全量重建换掉整个索引。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import library as LIB
from nihonco_player.core.library import CACHE


def item(uid, title):
    return {"key": uid, "uid": uid, "file": f"/tmp/{uid}.mp3", "stem": f"X - {title}",
            "orig": title, "title": title, "artist": "X", "group": "",
            "has_lyric": False, "lang": "unknown", "suspect": False}


class TestCacheRefresh(unittest.TestCase):
    def setUp(self):
        self.old = dict(CACHE)
        CACHE.clear()
        CACHE.update({"0": item("u1", "A"), "1": item("u2", "B")})

    def tearDown(self):
        CACHE.clear()
        CACHE.update(self.old)

    def test_single_uid_replaces_in_place(self):
        with patch.object(LIB, "scan_library", side_effect=AssertionError("不该全库扫描")), \
             patch.object(LIB, "_entry", return_value=item("u1", "A2")):
            n = LIB.refresh("u1")
        self.assertEqual(n, 2)
        self.assertEqual(CACHE["0"]["title"], "A2")
        self.assertEqual(CACHE["1"]["title"], "B")     # 其它条目没动

    def test_unknown_uid_falls_back_to_full_refresh(self):
        # 新出现的歌（uid 不在 CACHE 里）→ 全量重建
        with patch.object(LIB, "scan_library", return_value=[item("u2", "B2")]):
            n = LIB.refresh("nope")
        self.assertEqual(n, 1)
        self.assertEqual(CACHE["0"]["title"], "B2")

    def test_add_paths_appends_without_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "X - A.mp3"; a.touch()
            b = Path(tmp) / "X - B.mp3"; b.touch()
            with patch.object(LIB, "scan_library", side_effect=AssertionError("不该全库扫描")), \
                 patch.object(LIB, "FP") as fp, \
                 patch.object(LIB, "_entry", side_effect=lambda p, g: item(str(p), p.stem)):
                fp.flush.return_value = None
                out = LIB.add_paths([a, b, a])
            self.assertEqual(len(out), 2)
            self.assertEqual(list(CACHE), ["0", "1", "2", "3"])
            self.assertEqual(CACHE["2"]["title"], "X - A")
            self.assertEqual(CACHE["3"]["title"], "X - B")

    def test_full_refresh_rebuilds(self):
        with patch.object(LIB, "scan_library", return_value=[item("u3", "C")]):
            n = LIB.refresh()
        self.assertEqual(n, 1)
        self.assertEqual(list(CACHE), ["0"])
        self.assertEqual(CACHE["0"]["title"], "C")


if __name__ == "__main__":
    unittest.main()
