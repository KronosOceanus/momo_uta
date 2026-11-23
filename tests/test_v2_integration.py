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
