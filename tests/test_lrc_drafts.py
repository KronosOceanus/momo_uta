"""LRC 草稿保存并重新打开时，保留尚未打点的歌词。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_files as lrcio, library, lyrics_cache


class TestLrcDrafts(unittest.TestCase):
    def test_save_and_reopen_draft(self):
        rows = [
            {"t": None, "text": "  まだ  "},
            {"t": 5.0, "text": "あの日"},
            {"t": None, "text": "そして"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - テスト.mp3"
            audio.touch()
            with patch.object(lyrics_cache, "CACHE", root / "cache"), \
                 patch.object(lrcio, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(lrcio.LY, "audio_duration", return_value=60), \
                 patch.object(library, "load_imports", return_value=[]):
                self.assertTrue(lrcio.save(audio, rows)["ok"])
                self.assertEqual(lrcio.load(audio)["lines"], rows)
                entries = library.scan_library(root)
                self.assertEqual(len(entries), 1)
                self.assertTrue(entries[0]["has_lyric"])

    def test_netease_formats_remain_timed(self):
        rows = lrcio.parse(
            '[00:00.00-1] 作詞 : X\n'
            '{"t":1234,"c":[{"tx":"あの日"}]}\n'
        )
        self.assertEqual(rows, [
            {"t": 0.0, "text": "作詞 : X"},
            {"t": 1.23, "text": "あの日"},
        ])


    def test_save_preserves_metadata_but_keeps_lyric_markers_editable(self):
        raw = "\ufeff [ar:歌手][ti:曲] \n[Chorus]\n[offset:500]\n[00:05.00]あの日\n[Note: keep singing]\n"
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            with patch.object(lrcio, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(lrcio.LY, "audio_duration", return_value=60), \
                 patch.object(lrcio.LY, "write_local_lrc") as cache_write:
                store = lrcio.store_path(audio)
                store.parent.mkdir(parents=True, exist_ok=True)
                store.write_text(raw, encoding="utf-8")
                draft = lrcio.load(audio)
                self.assertEqual([row["text"] for row in draft["lines"]],
                                 ["[Chorus]", "あの日", "[Note: keep singing]"])
                self.assertEqual([tag["before"] for tag in draft["metadata"]], [0, 1])
                draft["lines"][1]["text"] = "次の日"
                self.assertTrue(lrcio.save(audio, draft["lines"])["ok"])
                doc = lrcio.load(audio)
                self.assertEqual([r["text"] for r in doc["lines"]],
                                 ["[Chorus]", "次の日", "[Note: keep singing]"])
                self.assertTrue(lrcio.store_path(audio).is_file())
                self.assertEqual(lrcio.backup_path(audio, lrcio.uid_of(audio))
                                 .read_text(encoding="utf-8"), raw)

    def test_first_save_carries_metadata_from_cache(self):
        raw = "[ar:歌手]\n[00:05.00]あの日\n"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(lrcio, "LYRICS", Path(tmp) / "lyrics"), \
             patch.object(lrcio.LY, "_cached", return_value=True), \
             patch.object(lrcio.LY, "get_lrc", return_value={"lrc": raw}), \
             patch.object(lrcio.LY, "audio_duration", return_value=60), \
             patch.object(lrcio.LY, "write_local_lrc"):
            audio = Path(tmp) / "歌手 - 曲.mp3"
            draft = lrcio.load(audio)
            self.assertTrue(draft["from_cache"])
            self.assertTrue(lrcio.save(audio, draft["lines"])["ok"])
            doc = lrcio.load(audio)
            self.assertEqual([r["text"] for r in doc["lines"]], ["あの日"])
            self.assertTrue(lrcio.store_path(audio).is_file())
            self.assertFalse((Path(tmp) / "歌手 - 曲.lrc").exists())
