"""歌单批量移动：跨歌单整组移动、同歌单多选重排。"""
import tempfile
import unittest
from pathlib import Path

from momo_player.core import playlists as PL


class TestMoveMany(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = PL.FILE
        PL.set_file(Path(self.tmp.name) / "playlists.json")
        PL.add("default", ["a", "b", "c", "d"])

    def tearDown(self):
        PL.set_file(self.old)
        self.tmp.cleanup()

    def test_cross_playlist_insert_before(self):
        lid = PL.create("目标")
        PL.add(lid, ["x", "y"])
        PL.move_many("default", lid, ["b", "d"], "y")
        d = PL.load()
        self.assertEqual(d["members"]["default"], ["a", "c"])
        self.assertEqual(d["members"][lid], ["x", "b", "d", "y"])

    def test_same_playlist_reorder_many(self):
        PL.move_many("default", "default", ["b", "d"], "c")
        self.assertEqual(PL.load()["members"]["default"], ["a", "b", "d", "c"])

    def test_cross_playlist_without_before_appends(self):
        lid = PL.create("目标")
        PL.add(lid, ["x"])
        PL.move_many("default", lid, ["b", "d"])
        d = PL.load()
        self.assertEqual(d["members"]["default"], ["a", "c"])
        self.assertEqual(d["members"][lid], ["x", "b", "d"])

    def test_missing_uids_ignored(self):
        lid = PL.create("目标")
        PL.move_many("default", lid, ["nope", "b"])
        d = PL.load()
        self.assertEqual(d["members"]["default"], ["a", "c", "d"])
        self.assertEqual(d["members"][lid], ["b"])


if __name__ == "__main__":
    unittest.main()
