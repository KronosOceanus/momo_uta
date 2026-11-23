"""歌词 v2 单一行模型：body/rows 往返、metadata、空行、译文。"""
import unittest

from nihonco_player.core import lyric_rows as R


class TestLyricRows(unittest.TestCase):
    def test_body_rows_keep_metadata_blank_timed_blank_and_trailing_blank(self):
        text = ("[ar:歌手]\n[00:01.00]君\n\n[00:02.00]\n"
                "[00:03.00]花\n\n")
        rows = R.parse_rows(text)
        self.assertEqual([r["kind"] for r in rows],
                         ["metadata", "lyric", "blank", "blank", "lyric", "blank"])
        self.assertEqual(rows[0]["text"], "[ar:歌手]")
        self.assertEqual((rows[1]["text"], rows[1]["t"]), ("君", 1.0))
        self.assertIsNone(rows[2]["t"])
        self.assertEqual(rows[3]["t"], 2.0)
        self.assertEqual((rows[4]["text"], rows[4]["t"]), ("花", 3.0))

    def test_v2_roundtrip_keeps_order_translation_and_lid(self):
        rows = [
            {"kind": "metadata", "text": "[ar:X]", "t": None},
            {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_aaa",
             "tokens": [{"tid": "t_aaa", "start": 0, "end": 1,
                         "base": "君", "ruby": "きみ", "level": "A"}],
             "trans": "你"},
            {"kind": "blank", "text": "", "t": None},
            {"kind": "blank", "text": "", "t": 2.0},
            {"kind": "lyric", "text": "花", "t": 3.0, "lid": "l_bbb",
             "tokens": [], "trans": "花"},
            {"kind": "blank", "text": "", "t": None},
        ]
        text = R.render_rows(rows, trans_lang="en")
        got = R.parse_rows(text)
        self.assertIn('"v": 2', text)
        self.assertIn('"trans_lang": "en"', text)
        self.assertEqual([r["kind"] for r in got],
                         ["metadata", "lyric", "blank", "blank", "lyric", "blank"])
        self.assertEqual([r.get("lid") for r in got],
                         [None, "l_aaa", None, None, "l_bbb", None])
        self.assertEqual(got[1]["trans"], "你")
        self.assertEqual(got[4]["trans"], "花")
        self.assertEqual(got[3]["t"], 2.0)
        self.assertEqual(got[1]["tokens"][0]["tid"], "t_aaa")

    def test_translation_without_tokens_still_writes_line_entry(self):
        rows = [{"kind": "lyric", "text": "花", "t": 1.0, "lid": "l_bbb",
                 "tokens": [], "trans": "花"}]
        text = R.render_rows(rows)
        self.assertIn('"seg": []', text)
        self.assertIn('"tid": []', text)
        got = R.parse_rows(text)
        self.assertEqual(got[0]["trans"], "花")

    def test_v1_tail_is_rejected(self):
        with self.assertRaises(ValueError):
            R.parse_rows("[00:01.00]君\n\n#NHLRC 1\n{\"v\":1}\n")

    def test_playable_sorts_by_time_then_document_order(self):
        rows = [
            {"kind": "lyric", "text": "late", "t": 9.0},
            {"kind": "blank", "text": "", "t": None},
            {"kind": "lyric", "text": "first", "t": 2.0},
            {"kind": "lyric", "text": "tie-a", "t": 9.0},
            {"kind": "lyric", "text": "tie-b", "t": 9.0},
        ]
        self.assertEqual([r["text"] for r in R.playable(rows)],
                         ["first", "late", "tie-a", "tie-b"])


if __name__ == "__main__":
    unittest.main()


class TestRowsStorage(unittest.TestCase):
    def test_v2_save_and_load_rows(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            rows = [
                {"kind": "metadata", "text": "[ar:X]", "t": None},
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_aaa",
                 "tokens": [{"tid": "t_aaa", "start": 0, "end": 1,
                             "base": "君", "ruby": "きみ", "level": "A"}],
                 "trans": "你"},
                {"kind": "blank", "text": "", "t": None},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LRF.save_rows(audio, rows)
                self.assertTrue(saved["ok"])
                loaded = LRF.load_rows(audio)
                self.assertTrue(loaded["ok"])
                self.assertEqual([r["kind"] for r in loaded["rows"]],
                                 ["metadata", "lyric", "blank"])
                self.assertEqual(loaded["rows"][1]["lid"], "l_aaa")
                self.assertEqual(loaded["rows"][1]["trans"], "你")
                self.assertEqual(loaded["rows"][1]["tokens"][0]["tid"], "t_aaa")

    def test_v2_rejects_v1_and_version_conflict(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LRF.save_rows(audio, [{"kind": "lyric", "text": "君", "t": 1.0,
                                               "lid": "l_aaa", "tokens": [], "trans": ""}])
                self.assertTrue(saved["ok"])
                conflict = LRF.save_rows(audio, [], expected_version="wrong")
                self.assertTrue(conflict.get("conflict"))
                path = LRF.store_path(audio)
                path.write_text("[00:01.00]君\n\n#NHLRC 1\n{\"v\":1}\n", encoding="utf-8")
                bad = LRF.load_rows(audio)
                self.assertFalse(bad["ok"])


class TestRowsService(unittest.TestCase):
    def test_service_save_load_rows(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF
        from nihonco_player.core import library as LIB
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import lyric_document as LD

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            uid = LRF.uid_of(audio)
            item = {"key": "k", "uid": uid, "file": str(audio),
                    "stem": "曲", "orig": "曲", "title": "曲", "artist": "歌手",
                    "has_lyric": True, "group": ""}
            CACHE.clear()
            CACHE["0"] = item
            LIB.BY_UID[uid] = item
            rows = [{"kind": "lyric", "text": "君", "t": 1.0,
                     "lid": "l_aaa", "tokens": [], "trans": "你"}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LD.save_rows(uid, rows)
                self.assertTrue(saved["ok"], saved)
                loaded = LD.load_rows(uid)
                self.assertTrue(loaded["ok"], loaded)
                self.assertEqual(loaded["rows"][0]["lid"], "l_aaa")
                self.assertEqual(loaded["rows"][0]["trans"], "你")


class TestRowsEditReading(unittest.TestCase):
    def test_edit_reading_by_lid_and_tid(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF
        from nihonco_player.core import library as LIB
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import lyric_document as LD

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            uid = LRF.uid_of(audio)
            item = {"key": "k", "uid": uid, "file": str(audio),
                    "stem": "曲", "orig": "曲", "title": "曲", "artist": "歌手",
                    "has_lyric": True, "group": ""}
            CACHE.clear()
            CACHE["0"] = item
            LIB.BY_UID[uid] = item
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_aaa",
                     "tokens": [{"tid": "t_aaa", "start": 0, "end": 1,
                                 "base": "君", "ruby": "きみ", "level": "AB"}],
                     "trans": ""}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LD.save_rows(uid, rows)["ok"])
                out = LD.edit_reading(uid, "l_aaa", "t_aaa", "きみだ")
                self.assertTrue(out["ok"], out)
                got = LD.load_rows(uid)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみだ")
                self.assertEqual(got["rows"][0]["tokens"][0]["level"], "A")
