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

    def test_v1_file_is_rejected(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, [{"kind": "lyric", "text": "君",
                                                       "t": 1.0, "lid": "l_aaa",
                                                       "tokens": [], "trans": ""}])["ok"])
                path = LRF.store_path(audio)
                path.write_text("[00:01.00]君\n\n#NHLRC 1\n{\"v\":1}\n",
                                encoding="utf-8")
                got = LRF.load_rows(audio)
                self.assertFalse(got["ok"])
                self.assertIn("不支持", got["error"])


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


class TestRowsPlayback(unittest.TestCase):
    def test_playback_uses_time_order_and_body_index(self):
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
            rows = [
                {"kind": "lyric", "text": "late", "t": 9.0, "lid": "l_late",
                 "tokens": [], "trans": ""},
                {"kind": "blank", "text": "", "t": None},
                {"kind": "lyric", "text": "first", "t": 2.0, "lid": "l_first",
                 "tokens": [], "trans": ""},
                {"kind": "lyric", "text": "tie", "t": 9.0, "lid": "l_tie",
                 "tokens": [], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LD.save_rows(uid, rows)["ok"])
                out = LD.playback(uid)
                self.assertTrue(out["ok"], out)
                self.assertEqual([x["text"] for x in out["lines"]],
                                 ["first", "late", "tie"])
                self.assertEqual(out["lines"][0]["body_index"], 2)
                self.assertEqual(out["lines"][1]["lid"], "l_late")


class TestRowOperations(unittest.TestCase):
    def test_split_keeps_lid_on_content_side_and_moves_tokens(self):
        row = {"id": "r1", "kind": "lyric", "text": "君の名", "t": 1.0,
               "lid": "l_aaa", "trans": "你的名字",
               "tokens": [
                   {"tid": "t1", "start": 0, "end": 1, "base": "君", "ruby": "きみ", "level": "A"},
                   {"tid": "t2", "start": 1, "end": 2, "base": "の", "ruby": None, "level": "K"},
                   {"tid": "t3", "start": 2, "end": 3, "base": "名", "ruby": "な", "level": "A"},
               ]}
        left, right = R.split_row(row, 2)
        self.assertEqual((left["text"], left["lid"]), ("君の", "l_aaa"))
        self.assertEqual(left["trans"], "你的名字")
        self.assertEqual([t["tid"] for t in left["tokens"]], ["t1", "t2"])
        self.assertEqual((right["text"], right["lid"]), ("名", right["lid"]))
        self.assertEqual(right["trans"], "")
        self.assertEqual([t["tid"] for t in right["tokens"]], ["t3"])
        self.assertEqual(right["tokens"][0]["start"], 0)

    def test_split_at_start_moves_lid_to_right(self):
        row = {"id": "r1", "kind": "lyric", "text": "君", "t": 1.0,
               "lid": "l_aaa", "trans": "你", "tokens": []}
        left, right = R.split_row(row, 0)
        self.assertEqual(left["kind"], "blank")
        self.assertEqual(right["lid"], "l_aaa")
        self.assertEqual(right["trans"], "你")

    def test_merge_joins_tokens_and_translations_in_document_order(self):
        left = {"id": "r1", "kind": "lyric", "text": "君", "t": 1.0,
                "lid": "l_aaa", "trans": "你",
                "tokens": [{"tid": "t1", "start": 0, "end": 1, "base": "君"}]}
        right = {"id": "r2", "kind": "lyric", "text": "花", "t": 2.0,
                 "lid": "l_bbb", "trans": "花",
                 "tokens": [{"tid": "t2", "start": 0, "end": 1, "base": "花"}]}
        out = R.merge_rows(left, right)
        self.assertEqual(out["text"], "君花")
        self.assertEqual(out["lid"], "l_aaa")
        self.assertEqual(out["trans"], "你 花")
        self.assertEqual([t["tid"] for t in out["tokens"]], ["t1", "t2"])
        self.assertEqual(out["tokens"][1]["start"], 1)


class TestV2Payload(unittest.TestCase):
    def test_song_payload_uses_v2_playable_rows(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF
        from nihonco_player.core import library as LIB
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import song as SONG

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
            rows = [
                {"kind": "lyric", "text": "late", "t": 9.0, "lid": "l_late",
                 "tokens": [], "trans": ""},
                {"kind": "blank", "text": "", "t": None},
                {"kind": "lyric", "text": "first", "t": 2.0, "lid": "l_first",
                 "tokens": [], "trans": "第一"},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                out = SONG.song_payload(uid)
                self.assertFalse(out["pending"])
                self.assertEqual([x["text"] for x in out["lines"]], ["first", "late"])
                self.assertEqual(out["lines"][0]["trans"], "第一")


class TestV2EditLine(unittest.TestCase):
    def test_old_line_start_api_maps_to_lid_tid(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF
        from nihonco_player.core import library as LIB
        from nihonco_player.core.library import CACHE
        from nihonco_player.service import song as SONG

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
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                out = SONG.edit_line(uid, 0, 0, "きみだ")
                self.assertTrue(out)
                got = LRF.load_rows(audio)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみだ")


class TestUtf16Spans(unittest.TestCase):
    def test_token_spans_after_surrogate_are_utf16(self):
        rows = [{"kind": "lyric", "text": "𠮷君", "t": 1.0, "lid": "l_a",
                 "tokens": [
                     {"tid": "t1", "start": 0, "end": 2, "base": "𠮷", "ruby": None, "level": "K"},
                     {"tid": "t2", "start": 2, "end": 3, "base": "君", "ruby": "きみ", "level": "A"},
                 ], "trans": ""}]
        text = R.render_rows(rows)
        got = R.parse_rows(text)
        toks = got[0]["tokens"]
        self.assertEqual([(t["start"], t["end"]) for t in toks], [(0, 2), (2, 3)])
        self.assertEqual(toks[1]["base"], "君")


class TestMalformedTail(unittest.TestCase):
    def test_bad_tail_types_are_ignored(self):
        cases = [
            '{"v":2,"lines":123}',
            '{"v":2,"lines":[1]}',
            '{"v":2,"lines":[{"i":0,"seg":1}]}',
            '{"v":2,"trans":123}',
            '{"v":2,"trans":[1]}',
        ]
        for tail in cases:
            text = "[00:01.00]君\n\n#NHLRC 2\n" + tail + "\n"
            rows = R.parse_rows(text)
            self.assertEqual(rows[0]["text"], "君")
            self.assertEqual(rows[0]["tokens"], [])
