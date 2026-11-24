"""导入配对：同一首歌同时有 .lrc 与 .nhlrc 时，优先 .nhlrc。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import importing, lrc_files as LRF, lyrics_cache, lyric_rows as R


class TestImportPreferNhlrc(unittest.TestCase):
    def test_nhlrc_wins_over_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            (root / "歌手 - 曲.lrc").write_text(
                "[00:05.00]旧歌词\n[00:10.00]第二句\n[00:15.00]第三句\n",
                encoding="utf-8")
            rows = [
                {"kind": "lyric", "text": "新歌词", "t": 5.0, "lid": "l_a",
                 "tokens": [{"tid": "t_a", "start": 0, "end": 1,
                             "base": "新", "ruby": "あら", "level": "A"},
                            {"tid": "t_b", "start": 1, "end": 3,
                             "base": "歌词", "ruby": None, "level": None}]},
                {"kind": "lyric", "text": "第二句", "t": 10.0, "lid": "l_b",
                 "tokens": []},
                {"kind": "lyric", "text": "第三句", "t": 15.0, "lid": "l_c",
                 "tokens": []},
            ]
            (root / "歌手 - 曲.nhlrc").write_text(R.render_rows(rows), encoding="utf-8")
            with patch.object(lyrics_cache, "CACHE", root / "cache"), \
                 patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = importing.import_paths([str(audio)], with_lrc=True)
                self.assertEqual(len(res["added"]), 1)
                doc = LRF.load(audio)            # 只读缓存，没有本地 .lrc/.nhlrc 冲突
                self.assertEqual([r["text"] for r in doc["lines"]][0], "新歌词")
                # 导入 nhlrc 时标注一并进缓存（不丢读音）
                self.assertEqual(doc["annotations"],
                                 {0: [["新", "あら", "A"], ["歌词", None, None]]})

    def test_audio_only_ignores_local_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            (root / "歌手 - 曲.lrc").write_text(
                "[00:05.00]本地歌词\n[00:10.00]第二句\n[00:15.00]第三句\n",
                encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = importing.import_paths([str(audio)])
                self.assertEqual(res["lrc_found"], 0)
                self.assertEqual(res["pending"], [str(audio)])
                self.assertFalse(LRF.store_path(audio).is_file())

    def test_audio_only_rejects_explicit_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            lrc = root / "歌手 - 曲.lrc"
            audio.touch()
            lrc.write_text("[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n",
                           encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = importing.import_paths([str(audio), str(lrc)])
                self.assertEqual(res["rejected_lrc"], 1)
                self.assertFalse(LRF.store_path(audio).is_file())

    def test_import_with_lrc_counts_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            lrc = root / "歌手 - 曲.lrc"
            audio.touch()
            lrc.write_text("[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n",
                           encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                first = importing.import_paths([str(audio), str(lrc)], with_lrc=True)
                second = importing.import_paths([str(audio), str(lrc)], with_lrc=True)
                self.assertEqual(first["overwritten"], 0)
                self.assertEqual(second["overwritten"], 1)

    def test_import_deduplicates_file_and_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            lrc = root / "歌手 - 曲.lrc"
            audio.touch()
            lrc.write_text("[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n",
                           encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = importing.import_paths([str(audio), str(root)], with_lrc=True)
                self.assertEqual(res["added"], [str(audio)])
                self.assertEqual(res["overwritten"], 0)

    def test_import_text_keeps_nhlrc_readings(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            text = R.render_rows([{"kind": "lyric", "text": "君", "t": 1.0,
                                   "lid": "l_aaa",
                                   "tokens": [{"tid": "t_aaa", "start": 0, "end": 1,
                                               "base": "君", "ruby": "きみ", "level": "A"}]}])
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = LRF.import_text(audio, text)
                self.assertTrue(res["ok"])
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                doc = LRF.load(audio)
            self.assertIn("#NHLRC", raw)                 # 读音一起导入
            self.assertIn("[00:01.00]君", raw)
            self.assertEqual(doc["annotations"], {0: [["君", "きみ", "A"]]})


if __name__ == "__main__":
    unittest.main()


class TestImportFailure(unittest.TestCase):
    def _env(self, root):
        audio = root / "歌手 - 曲.mp3"
        lrc = root / "歌手 - 曲.lrc"
        audio.touch()
        lrc.write_text("[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n", encoding="utf-8")
        return audio, lrc

    def test_lrc_import_failure_keeps_audio_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, lrc = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF, "import_text",
                              return_value={"ok": False, "error": "disk full"}):
                res = importing.import_paths([str(audio), str(lrc)], with_lrc=True)
            self.assertIn(str(audio), res["added"])
            self.assertIn(str(audio), res["pending"])
            self.assertEqual(res["failed_count"], 1)
            self.assertIn("disk full", res["failed"][0]["error"])

    def test_lrc_import_exception_keeps_audio_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, lrc = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF, "import_text", side_effect=OSError("boom")):
                res = importing.import_paths([str(audio), str(lrc)], with_lrc=True)
            self.assertIn(str(audio), res["pending"])
            self.assertEqual(res["failed_count"], 1)
            self.assertIn("boom", res["failed"][0]["error"])


class TestStrictPairing(unittest.TestCase):
    def test_exact_song_beats_numbered_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            song = root / "Song.mp3"; song.write_bytes(b"song-audio")
            numbered = root / "01 Song.mp3"; numbered.write_bytes(b"numbered-audio")
            (root / "Song.lrc").write_text(
                "[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n", encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                res = importing.import_paths([str(root)], with_lrc=True)
                self.assertIn(str(song), res["added"])
                self.assertIn(str(numbered), res["pending"])
                self.assertTrue(LRF.store_path(song).is_file())
                self.assertFalse(LRF.store_path(numbered).is_file())

    def test_same_dir_exact_wins_over_other_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "A" / "Song.mp3"; b = root / "B" / "Song.mp3"
            a.parent.mkdir(); b.parent.mkdir(); a.touch(); b.touch()
            (b.parent / "Song.lrc").write_text(
                "[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n", encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                res = importing.import_paths([str(root)], with_lrc=True)
                self.assertIn(str(b), res["added"])
                self.assertIn(str(a), res["pending"])
                self.assertTrue(LRF.store_path(b).is_file())

    def test_multiple_different_lrc_bases_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "Song.mp3"; audio.touch()
            (root / "Song (1).lrc").write_text(
                "[00:05.00]君\n[00:10.00]花\n[00:15.00]夜\n", encoding="utf-8")
            (root / "Song (2).lrc").write_text(
                "[00:05.00]別\n[00:10.00]歌\n[00:15.00]詞\n", encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                res = importing.import_paths([str(root)], with_lrc=True)
            self.assertIn(str(audio), res["pending"])
            self.assertEqual(res["ambiguous"], 1)
            self.assertFalse(LRF.store_path(audio).is_file())
