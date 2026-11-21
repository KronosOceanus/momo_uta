"""曲库重排后，uid 必须仍然指向同一首歌。"""
import tempfile
import unittest
from pathlib import Path

from nihonco_player.core import library as LIB


class TestLibraryIdentity(unittest.TestCase):
    def setUp(self):
        self.cache = dict(LIB.CACHE)
        self.by_uid = dict(LIB.BY_UID)

    def tearDown(self):
        LIB.CACHE.clear()
        LIB.CACHE.update(self.cache)
        LIB.BY_UID.clear()
        LIB.BY_UID.update(self.by_uid)

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
        self.assertIsNone(LIB.resolve("0"))     # idx 不再是身份
        self.assertIsNone(LIB.resolve("1"))

    def test_idx_is_not_a_song_identity(self):
        a = {"uid": "aaa", "title": "A", "file": "/tmp/a.mp3"}
        b = {"uid": "bbb", "title": "B", "file": "/tmp/b.mp3"}
        LIB._publish([a, b])
        self.assertIsNone(LIB.resolve("0"))
        self.assertIs(LIB.resolve("aaa"), a)

    def test_refresh_removes_old_uid_mapping(self):
        from unittest.mock import patch
        old = {"uid": "old", "title": "A", "file": "/tmp/a.mp3"}
        new = {"uid": "new", "title": "A", "file": "/tmp/a.mp3"}
        LIB.CACHE.clear(); LIB.CACHE["0"] = old
        LIB.BY_UID.clear(); LIB.BY_UID["old"] = old
        with patch.object(LIB, "_entry", return_value=new), \
             patch.object(LIB.LI, "flush"):
            LIB.refresh("old")
        self.assertNotIn("old", LIB.BY_UID)
        self.assertIs(LIB.BY_UID["new"], new)
        self.assertIs(LIB.CACHE["0"], new)

    def test_refresh_keeps_old_uid_if_another_copy_remains(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.mp3"; a.touch()
            c = Path(tmp) / "a-copy.mp3"; c.touch()
            old = {"uid": "same", "title": "A", "file": str(a)}
            copy = {"uid": "same", "title": "A", "file": str(c)}
            new = {"uid": "new", "title": "A", "file": str(a)}
            LIB.CACHE.clear(); LIB.CACHE["0"] = old; LIB.CACHE["1"] = copy
            LIB.BY_UID.clear(); LIB.BY_UID["same"] = old
            def entry(path, group, **kw):
                return new if str(path) == str(a) else copy
            with patch.object(LIB, "_entry", side_effect=entry), \
                 patch.object(LIB.LI, "flush"):
                LIB.refresh("same")
            self.assertIs(LIB.BY_UID["same"], copy)   # 旧 uid 指向剩余副本
            self.assertIs(LIB.BY_UID["new"], new)
            self.assertIs(LIB.CACHE["0"], new)

    def test_refresh_live_copy_not_stale_cache(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            old = "old"
            a, b, c = (Path(tmp) / n for n in ("a.mp3", "b.mp3", "c.mp3"))
            for p in (a, b, c): p.touch()
            ea = {"uid": old, "title": "A", "file": str(a), "group": ""}
            eb = {"uid": old, "title": "A", "file": str(b), "group": ""}
            ec = {"uid": old, "title": "A", "file": str(c), "group": ""}
            LIB.CACHE.clear(); LIB.CACHE.update({"0": ea, "1": eb, "2": ec})
            LIB.BY_UID.clear(); LIB.BY_UID[old] = ea

            def entry(path, group, **kw):
                f = str(path)
                return {"uid": "new-" + f[-5:], "file": f, "title": "A", "group": group}

            with patch.object(LIB, "_entry", side_effect=entry), \
                 patch.object(LIB.LI, "flush"):
                LIB.refresh(old)
            self.assertNotIn(old, LIB.BY_UID)       # B/C 都已替换

    def test_refresh_keeps_live_copy_after_stale_sibling(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            old = "old"
            a, b, c = (Path(tmp) / n for n in ("a.mp3", "b.mp3", "c.mp3"))
            for p in (a, b, c): p.touch()
            ea = {"uid": old, "title": "A", "file": str(a), "group": ""}
            eb = {"uid": old, "title": "A", "file": str(b), "group": ""}
            ec = {"uid": old, "title": "A", "file": str(c), "group": ""}
            LIB.CACHE.clear(); LIB.CACHE.update({"0": ea, "1": eb, "2": ec})
            LIB.BY_UID.clear(); LIB.BY_UID[old] = ea

            def entry(path, group, **kw):
                f = str(path)
                return {"uid": old if f == str(c) else "new-" + f[-5:],
                        "file": f, "title": "A", "group": group}

            with patch.object(LIB, "_entry", side_effect=entry), \
                 patch.object(LIB.LI, "flush"):
                LIB.refresh(old)
            self.assertEqual(LIB.BY_UID[old]["file"], str(c))   # 只有 C 仍然匹配
            self.assertEqual(LIB.BY_UID[old]["file"], str(c))

    def test_real_wav_three_copies_uses_live_file(self):
        import struct
        import wave
        from unittest.mock import patch
        from nihonco_player.core import fingerprint as FP
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / n for n in ("a.wav", "b.wav", "c.wav")]
            def make(path, sample):
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
                    w.writeframes(struct.pack("<h", sample) * 800)
            make(paths[0], 100); make(paths[1], 100); make(paths[2], 100)
            uid = FP.fingerprint(paths[0], force=True)
            make(paths[0], 2000); make(paths[1], 3000)   # A/B 内容被替换，C 仍完好
            items = [{"uid": uid, "title": "A", "file": str(p), "group": ""}
                     for p in paths]
            LIB.CACHE.clear(); LIB.CACHE.update({str(i): x for i, x in enumerate(items)})
            LIB.BY_UID.clear(); LIB.BY_UID[uid] = items[0]
            with patch.object(LIB.LI, "put"), patch.object(LIB.LI, "flush"):
                LIB.refresh(uid)
            self.assertIn(uid, LIB.BY_UID)
            self.assertEqual(LIB.BY_UID[uid]["file"], str(paths[2]))
            self.assertNotEqual(FP.fingerprint(paths[0], force=True), uid)
            self.assertNotEqual(FP.fingerprint(paths[1], force=True), uid)

    def test_unknown_ref(self):
        LIB._publish([])
        self.assertIsNone(LIB.resolve("nope"))
        self.assertIsNone(LIB.idx_for("nope"))


if __name__ == "__main__":
    unittest.main()
