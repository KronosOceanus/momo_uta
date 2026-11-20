"""重新匹配：候选只来自网络；选中后重写歌词、读音重来。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import library as LIB
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import lyrics as LY
from nihonco_player.core import lyrics_cache as LC
from nihonco_player.core.library import CACHE
from nihonco_player.service import song as SONG


def item(audio):
    return {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
            "stem": audio.stem, "orig": "曲", "title": "曲",
            "artist": "歌手", "has_lyric": True, "group": ""}


class TestRematch(unittest.TestCase):
    def test_candidates_are_network_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear(); CACHE["0"] = item(audio)
            with patch.object(LY, "search_candidates", return_value=[]), \
                 patch.object(LY, "get_lrc", return_value={"id": 999, "lrc": "[00:01.00]旧"}):
                d = SONG.rematch(0, 60)
            self.assertEqual(d["candidates"], [])      # 不再把本地当前项插进来

    def test_current_marked_only_if_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear(); CACHE["0"] = item(audio)
            cand = {"id": 999, "name": "曲", "artist": "歌手", "duration": 60.0}
            with patch.object(LY, "search_candidates", return_value=[cand]), \
                 patch.object(LY, "get_lrc", return_value={"id": 999, "lrc": "[00:01.00]旧"}):
                d = SONG.rematch(0, 60)
            self.assertTrue(d["candidates"][0]["current"])

    def test_pick_rewrites_lyrics_and_resets_readings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear(); CACHE["0"] = item(audio)
            new = "[00:05.00]新しい歌詞\n[00:09.00]二行目\n[00:13.00]三行目\n"
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LIB, "refresh", return_value=1), \
                 patch.object(LY, "fetch_lrc_by_id", return_value=new):
                LRF.save(audio, [{"t": 1.0, "text": "旧歌词"}],
                         {0: [["旧歌词", "ふるうた", "A"]]})
                res = SONG.pick("0", 123)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                doc = LRF.load(audio)
            self.assertTrue(res["ok"])
            self.assertIn("新しい歌詞", raw)
            self.assertNotIn("旧歌词", raw)
            self.assertNotIn("ふるうた", raw)          # 旧读音不保留
            self.assertEqual(doc["lines"][0]["text"], "新しい歌詞")


    def test_pick_rejects_untimed_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear(); CACHE["0"] = item(audio)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LY, "fetch_lrc_by_id", return_value="作词 : X\nあの日\n今も\n空を"):
                LRF.save(audio, [{"t": 1.0, "text": "旧歌词"}], {})
                before = LRF.store_path(audio).read_text(encoding="utf-8")
                res = SONG.pick("0", 123)
                after = LRF.store_path(audio).read_text(encoding="utf-8")
            self.assertFalse(res["ok"])
            self.assertIn("时间轴", res["error"])
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
