"""重新匹配：候选只来自网络；选中后重写歌词、读音重来。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import library as LIB
from momo_player.core import lrc_files as LRF
from momo_player.core import lyrics as LY
from momo_player.core import lyrics_cache as LC
from momo_player.core.library import CACHE
from momo_player.service import song as SONG


def item(audio):
    return {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
            "stem": audio.stem, "orig": "曲", "title": "曲",
            "artist": "歌手", "has_lyric": True, "group": ""}


class TestRematch(unittest.TestCase):
    def test_candidates_are_network_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            it = item(audio); CACHE.clear(); CACHE["0"] = it; LIB.BY_UID[it["uid"]] = it
            with patch.object(LY, "search_candidates_status",
                              return_value=([], "no_match")), \
                 patch.object(LY, "get_lrc", return_value={"id": 999, "lrc": "[00:01.00]旧"}):
                d = SONG.rematch(it["uid"], 60)
            self.assertEqual(d["candidates"], [])      # 不再把本地当前项插进来

    def test_rematch_does_not_touch_lyrics_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            it = item(audio); CACHE.clear(); CACHE["0"] = it; LIB.BY_UID[it["uid"]] = it
            cand = {"id": 999, "name": "曲", "artist": "歌手", "duration": 60.0}
            with patch.object(LY, "search_candidates_status",
                              return_value=([cand], "ok")), \
                 patch.object(LY, "get_lrc") as gl:
                d = SONG.rematch(it["uid"], 60)
            self.assertEqual(d["candidates"][0]["id"], 999)
            self.assertNotIn("current", d["candidates"][0])
            gl.assert_not_called()

    def test_pick_rewrites_lyrics_and_resets_readings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            it = item(audio); CACHE.clear(); CACHE["0"] = it; LIB.BY_UID[it["uid"]] = it
            new = "[00:05.00]新しい歌詞\n[00:09.00]二行目\n[00:13.00]三行目\n"
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LIB, "refresh", return_value=1), \
                 patch.object(LY, "fetch_lyrics_by_id",
                              return_value={"lrc": new, "tlyric": "[00:05.00]新翻译\n"}):
                LRF.save(audio, [{"t": 1.0, "text": "旧歌词"}],
                         {0: [["旧歌词", "ふるうた", "A"]]})
                res = SONG.pick(it["uid"], 123)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                doc = LRF.load(audio)
            self.assertTrue(res["ok"])
            self.assertIn("新しい歌詞", raw)
            self.assertNotIn("旧歌词", raw)
            self.assertNotIn("ふるうた", raw)          # 旧读音不保留
            self.assertEqual(doc["lines"][0]["text"], "新しい歌詞")
            self.assertEqual(doc["translations"], {0: "新翻译"})


    def test_pick_rejects_untimed_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            it = item(audio); CACHE.clear(); CACHE["0"] = it; LIB.BY_UID[it["uid"]] = it
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LY, "fetch_lyrics_by_id", return_value={"lrc": "作词 : X\nあの日\n今も\n空を", "tlyric": ""}):
                LRF.save(audio, [{"t": 1.0, "text": "旧歌词"}], {})
                before = LRF.store_path(audio).read_text(encoding="utf-8")
                res = SONG.pick(it["uid"], 123)
                after = LRF.store_path(audio).read_text(encoding="utf-8")
            self.assertFalse(res["ok"])
            self.assertIn("时间轴", res["error"])
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
