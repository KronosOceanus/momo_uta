"""v2 端到端：导入、API 读写、普通播放、改读音、v1 保存转换。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import importing as IMP
from nihonco_player.core import library as LIB
from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import lyrics_cache as LC
from nihonco_player.core.library import CACHE
from nihonco_player.service import lrc as SVC_LRC
from nihonco_player.service import song as SONG


def _item(audio):
    return {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
            "stem": audio.stem, "orig": "曲", "title": "曲",
            "artist": "歌手", "has_lyric": True, "group": ""}


def _cache(audio):
    item = _item(audio)
    CACHE.clear()
    CACHE["0"] = item
    LIB.BY_UID[item["uid"]] = item
    return item


class TestV2Integration(unittest.TestCase):
    def test_import_local_lrc_writes_v2_without_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            lrc = root / "歌手 - 曲.lrc"
            audio.touch()
            lrc.write_text("[00:01.00]君\n[00:02.00]花\n[00:03.00]夜\n",
                           encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = IMP.import_paths([str(audio), str(lrc)], with_lrc=True)
                self.assertEqual(len(res["added"]), 1)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", raw)
                doc = LRF.load_rows(audio)
                self.assertEqual(doc["model"], 2)
                self.assertEqual(doc["rows"][0]["kind"], "lyric")
                self.assertTrue(doc["rows"][0]["lid"].startswith("l_"))

    def test_v2_load_save_play_and_edit_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "metadata", "text": "[ar:X]", "t": None},
                {"kind": "lyric", "text": "君", "t": 2.0, "lid": "l_a",
                 "tokens": [], "trans": "你"},
                {"kind": "blank", "text": "", "t": None},
                {"kind": "lyric", "text": "花", "t": 1.0, "lid": "l_b",
                 "tokens": [], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                saved = LRF.save_rows(audio, rows)
                self.assertTrue(saved["ok"], saved)
                load = SVC_LRC.lrc_action({"action": "load", "uid": item["uid"]})
                self.assertEqual(load["model"], 2)
                self.assertEqual([r["kind"] for r in load["rows"]],
                                 ["metadata", "lyric", "blank", "lyric"])
                out = SVC_LRC.lrc_action({
                    "action": "save_rows", "uid": item["uid"],
                    "version": load["version"],
                    "rows": [{**r, "trans": "新译" if r["kind"] == "lyric" else r.get("trans", "")}
                             for r in load["rows"]],
                })
                self.assertTrue(out["ok"], out)
                again = LRF.load_rows(audio)
                self.assertEqual(again["rows"][1]["trans"], "新译")
                payload = SONG.song_payload(item["uid"])
                self.assertEqual([x["text"] for x in payload["lines"]], ["花", "君"])
                self.assertTrue(SONG.edit_line(item["uid"], 0, 0, "はな"))

    def test_v1_save_is_converted_to_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            v1 = DOC.render_nhlrc(
                [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}], [],
                {0: [["君", "きみ", "A"]], 1: [["花", "はな", "A"]]})
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
                LRF.store_path(audio).write_text(v1, encoding="utf-8")
                res = SONG.save_lyrics(item, [{"t": 1.0, "text": "君"},
                                              {"t": 2.0, "text": "花"}], "align")
                self.assertTrue(res["ok"], res)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", raw)
                self.assertNotIn("#NHLRC 1", raw)


class TestV2Contract(unittest.TestCase):
    def test_export_rows_is_v2_and_keeps_unsaved_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "你"}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LRF.save_rows(audio, rows)
                self.assertTrue(saved["ok"])
                out = SVC_LRC.lrc_action({
                    "action": "export", "uid": item["uid"],
                    "rows": [{"kind": "lyric", "text": "花", "t": 2.0,
                              "lid": "l_b", "tokens": [], "trans": "花"}]})
                self.assertTrue(out["ok"], out)
                self.assertIn("#NHLRC 2", out["nhlrc"])
                self.assertIn("l_b", out["nhlrc"])
                self.assertTrue(out["lrc"].startswith("[00:02.00]花"))

    def test_save_rows_without_trans_lang_preserves_existing_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "you"}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows, trans_lang="en")["ok"])
                out = SVC_LRC.lrc_action({
                    "action": "save_rows", "uid": item["uid"],
                    "rows": [{**rows[0], "trans": "you!"}]})
                self.assertTrue(out["ok"], out)
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")


class TestV2TokenRepair(unittest.TestCase):
    def test_partial_tokens_keep_reading_after_text_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            rows = [{"kind": "lyric", "text": "君の花", "t": 1.0, "lid": "l_a",
                     "tokens": [
                         {"tid": "t1", "start": 0, "end": 1, "base": "君", "ruby": "きみ", "level": "A"},
                         {"tid": "t2", "start": 1, "end": 2, "base": "の", "ruby": None, "level": "K"},
                     ], "trans": ""}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                item = _item(audio)
                item["file"] = str(audio)
                CACHE.clear(); CACHE["0"] = item; LIB.BY_UID[item["uid"]] = item
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                got = LRF.load_rows(audio)
                self.assertEqual(len(got["rows"][0]["tokens"]), 3)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみ")
                self.assertEqual(got["rows"][0]["tokens"][2]["base"], "花")


class TestV2StalePlaybackEdit(unittest.TestCase):
    def test_lid_relocated_after_playback_order_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_jun",
                 "tokens": [{"tid": "t_j", "start": 0, "end": 1, "base": "君",
                             "ruby": "きみ", "level": "A"}], "trans": ""},
                {"kind": "lyric", "text": "花", "t": 2.0, "lid": "l_hana",
                 "tokens": [{"tid": "t_h", "start": 0, "end": 1, "base": "花",
                             "ruby": "はな", "level": "A"}], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                payload = SONG.song_payload(item["uid"])
                self.assertEqual(payload["lines"][0]["lid"], "l_jun")
                # 文件顺序不变，但播放时间改成 花 在前。
                swapped = [dict(rows[0], t=2.0), dict(rows[1], t=1.0)]
                self.assertTrue(LRF.save_rows(audio, swapped)["ok"])
                out = SONG.edit_line_action({"uid": item["uid"], "line": 0,
                                             "lid": "l_jun", "start": 0,
                                             "reading": "きみだ"})
                self.assertIn("きみだ", out["ruby"])
                got = LRF.load_rows(audio)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみだ")
                self.assertEqual(got["rows"][1]["tokens"][0]["ruby"], "はな")
