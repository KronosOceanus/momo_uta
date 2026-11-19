"""导入配对：同一首歌同时有 .lrc 与 .nhlrc 时，优先 .nhlrc。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import importing, lrc_doc as DOC, lrc_files as LRF, lyrics_cache


class TestImportPreferNhlrc(unittest.TestCase):
    def test_nhlrc_wins_over_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            (root / "歌手 - 曲.lrc").write_text(
                "[00:05.00]旧歌词\n[00:10.00]第二句\n[00:15.00]第三句\n",
                encoding="utf-8")
            body = "[00:05.00]新歌词\n[00:10.00]第二句\n[00:15.00]第三句\n"
            ann = {0: [["新", "あら", "A"], ["歌词", None, None]]}
            (root / "歌手 - 曲.nhlrc").write_text(
                DOC.render_nhlrc(
                    [{"t": 5.0, "text": "新歌词"}, {"t": 10.0, "text": "第二句"},
                     {"t": 15.0, "text": "第三句"}], [], ann),
                encoding="utf-8")
            with patch.object(lyrics_cache, "CACHE", root / "cache"), \
                 patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = importing.import_paths([str(audio)])
                self.assertEqual(len(res["added"]), 1)
                doc = LRF.load(audio)            # 只读缓存，没有本地 .lrc/.nhlrc 冲突
                self.assertEqual([r["text"] for r in doc["lines"]][0], "新歌词")
                # 导入 nhlrc 时标注一并进缓存（不丢读音）
                self.assertEqual(doc["annotations"],
                                 {0: [["新", "あら", "A"], ["歌词", None, None]]})

    def test_import_text_strips_nhlrc_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            text = DOC.render_nhlrc([{"t": 1.0, "text": "君"}], [],
                                       {0: [["君", "きみ", "A"]]})
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "write_local_lrc"):
                res = LRF.import_text(audio, text)
                self.assertTrue(res["ok"])
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
            self.assertNotIn("#NHLRC", raw)
            self.assertIn("[00:01.00]君", raw)


if __name__ == "__main__":
    unittest.main()
