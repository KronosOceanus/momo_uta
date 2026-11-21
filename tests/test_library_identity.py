"""曲库重排后，uid 必须仍然指向同一首歌。"""
import unittest

from nihonco_player.core import library as LIB


class TestLibraryIdentity(unittest.TestCase):
    def setUp(self):
        self.cache = dict(LIB.CACHE)
        self.by_uid = dict(LIB.BY_UID)
        self.gen = LIB.GENERATION

    def tearDown(self):
        LIB.CACHE.clear()
        LIB.CACHE.update(self.cache)
        LIB.BY_UID.clear()
        LIB.BY_UID.update(self.by_uid)
        LIB.GENERATION = self.gen

    def test_uid_survives_reindex(self):
        a = {"uid": "aaa", "title": "A", "file": "/tmp/a.mp3"}
        b = {"uid": "bbb", "title": "B", "file": "/tmp/b.mp3"}
        LIB._publish([a, b])
        self.assertIs(LIB.resolve("aaa"), a)
        self.assertEqual(LIB.idx_for("aaa"), "0")

        LIB._publish([b, a])
        self.assertIs(LIB.resolve("aaa"), a)
        self.assertIs(LIB.resolve("bbb"), b)
        self.assertEqual(LIB.idx_for("aaa"), "1")
        self.assertEqual(LIB.idx_for("bbb"), "0")
        self.assertIs(LIB.resolve("0"), b)
        self.assertIs(LIB.resolve("1"), a)
        self.assertGreaterEqual(LIB.generation(), self.gen + 2)

    def test_unknown_ref(self):
        LIB._publish([])
        self.assertIsNone(LIB.resolve("nope"))
        self.assertIsNone(LIB.idx_for("nope"))


if __name__ == "__main__":
    unittest.main()
