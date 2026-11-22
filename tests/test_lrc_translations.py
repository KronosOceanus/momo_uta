"""nhlrc 尾部翻译的落盘与保留。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_files as LRF
from nihonco_player.service import song as SONG


class TestLrcTranslations(unittest.TestCase):
    def test_save_and_load_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"):
                audio = Path(tmp) / "曲.mp3"
                rows = [{"t": 1.0, "text": "君"}]
                r = LRF.save(audio, rows, uid="u1", title="曲", artist="歌手",
                             translations={0: "你"})
                self.assertTrue(r["ok"])
                doc = LRF.load(audio, "u1", "曲", "歌手")
                self.assertEqual(doc["translations"], {0: "你"})

    def test_saving_annotation_keeps_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"):
                audio = Path(tmp) / "曲.mp3"
                rows = [{"t": 1.0, "text": "君"}]
                LRF.save(audio, rows, uid="u1", title="曲", artist="歌手",
                         translations={0: "你"})
                LRF.save(audio, rows, annotations={0: [["君", "きみ", "A"]]},
                         uid="u1", title="曲", artist="歌手")
                doc = LRF.load(audio, "u1", "曲", "歌手")
                self.assertEqual(doc["translations"], {0: "你"})


if __name__ == "__main__":
    unittest.main()


class TestCacheTranslation(unittest.TestCase):
    def test_cache_tlyric_is_paired_on_load(self):
        from nihonco_player.core import lyrics as LY
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(LY, "get_lrc", return_value={
                     "lrc": "[00:01.00]君\n[00:02.00]花\n",
                     "tlyric": "[00:01.00]你\n[00:02.00]花\n"}):
                doc = LRF.load(Path(tmp) / "曲.mp3", "u1", "曲", "歌手")
                self.assertEqual(doc["translations"], {0: "你", 1: "花"})


class TestPayloadTranslation(unittest.TestCase):
    def test_payload_lines_carry_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"):
                audio = Path(tmp) / "曲.mp3"
                LRF.save(audio, [{"t": 1.0, "text": "君"}], uid="u1",
                         title="曲", artist="歌手", translations={0: "你"})
                item = {"uid": "u1", "file": str(audio), "key": "k",
                        "title": "曲", "artist": "歌手"}
                d = SONG.song_payload(None, item)
                self.assertEqual(d["lines"][0]["trans"], "你")
