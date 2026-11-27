"""LRC 草稿保存并重新打开时，保留尚未打点的歌词。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import lrc_files as lrcio, library, lyrics_cache


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

    def test_netease_formats_and_credit_are_classified(self):
        rows = lrcio.parse(
            '[00:00.00-1] 作詞 : X\n'
            '{"t":1234,"c":[{"tx":"あの日"}]}\n'
        )
        # 作詞 是 metadata，不进入播放 compact lines；JSON 歌词保留时间。
        self.assertEqual(rows, [
            {"t": 1.23, "text": "あの日"},
        ])


    def test_timed_credit_is_saved_as_metadata_with_timestamp(self):
        rows = [
            {"t": 0.0, "text": "作詞: X"},
            {"t": 5.0, "text": "君"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            with patch.object(lrcio, "LYRICS", root / "lyrics"), \
                 patch.object(lrcio.LY, "audio_duration", return_value=60):
                self.assertTrue(lrcio.save(audio, rows)["ok"])
                raw = lrcio.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("[00:00.00]作詞: X", raw)
                doc = lrcio.load(audio)
                self.assertEqual([x["text"] for x in doc["lines"]], ["君"])
                self.assertEqual([x["text"] for x in doc["metadata"]], ["作詞: X"])
                self.assertEqual(doc["metadata"][0]["t"], 0.0)

    def test_persist_cache_writes_full_doc_and_is_noop_for_nhlrc(self):
        from unittest.mock import patch
        from momo_player.service import song as SVC
        item = {"uid": "u0", "file": "/tmp/x.mp3", "title": "x", "artist": ""}
        cache = {"ok": True, "kind": "cache", "version": "none", "disabled": False,
                 "body_rows": [{"t": 1.0, "text": "君"}],
                 "lines": [{"t": 1.0, "text": "君"}],
                 "metadata": [{"before": 0, "text": "[ar:X]"}],
                 "trans_lang": "zh"}
        with patch.object(SVC, "load_lyrics", return_value=(cache, True)), \
             patch.object(SVC, "save_lyrics", return_value={"ok": True, "version": "v2"}) as save:
            res = SVC.persist_cache(item)
        self.assertTrue(res["ok"])
        self.assertFalse(res["already"])
        self.assertEqual(res["version"], "v2")
        self.assertEqual(save.call_args.args[1], cache["body_rows"])
        self.assertEqual(save.call_args.args[2], "align")

        nhlrc = {**cache, "kind": "nhlrc", "version": "v1"}
        with patch.object(SVC, "load_lyrics", return_value=(nhlrc, True)), \
             patch.object(SVC, "save_lyrics") as save:
            res = SVC.persist_cache(item)
        self.assertTrue(res["ok"])
        self.assertTrue(res["already"])
        self.assertEqual(res["version"], "v1")
        save.assert_not_called()

    def test_persist_cache_rejects_empty_lyrics(self):
        from unittest.mock import patch
        from momo_player.service import song as SVC
        empty = {"ok": True, "kind": "cache", "version": "none", "disabled": False,
                 "body_rows": [], "lines": [], "metadata": []}
        with patch.object(SVC, "load_lyrics", return_value=(empty, False)):
            res = SVC.persist_cache({"uid": "u0"})
        self.assertFalse(res["ok"])
        self.assertIn("没有可保存", res["error"])

    def test_persist_cache_rejects_unreadable_doc(self):
        from unittest.mock import patch
        from momo_player.service import song as SVC
        with patch.object(SVC, "load_lyrics",
                          return_value=({"ok": False, "error": "bad nhlrc"}, False)):
            res = SVC.persist_cache({"uid": "u0"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "bad nhlrc")

    def test_persist_cache_creates_real_nhlrc(self):
        from unittest.mock import patch
        from momo_player.service import song as SVC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            item = {"uid": "u0", "file": str(audio), "title": "曲", "artist": "歌手"}
            lrc = "[ar:歌手]\n[00:01.00]君\n[00:02.00]花\n"
            tlyric = "[00:01.00]你\n[00:02.00]花\n"
            with patch.object(lrcio, "LYRICS", root / "lyrics"), \
                 patch.object(lrcio.LY, "get_lrc",
                              return_value={"lrc": lrc, "tlyric": tlyric,
                                            "source": "test"}), \
                 patch.object(SVC.LIB, "refresh", return_value={}):
                res = SVC.persist_cache(item)
                self.assertTrue(res["ok"])
                self.assertFalse(res["already"])
                path = lrcio.store_path(audio, "u0", "曲", "歌手")
                self.assertTrue(path.is_file())
                doc = lrcio.load(audio, "u0", "曲", "歌手")
                self.assertEqual(doc["kind"], "nhlrc")
                self.assertEqual([x["text"] for x in doc["lines"]], ["君", "花"])

    def test_save_preserves_metadata_but_keeps_lyric_markers_editable(self):
        raw = "\ufeff [ar:歌手][ti:曲] \n[Chorus]\n[offset:500]\n[00:05.00]あの日\n[Note: keep singing]\n"
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            with patch.object(lrcio, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(lrcio.LY, "audio_duration", return_value=60):
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
                self.assertEqual(lrcio.store_backup(audio)
                                 .read_text(encoding="utf-8"), raw)

    def test_first_save_carries_metadata_from_cache(self):
        raw = "[ar:歌手]\n[00:05.00]あの日\n"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(lrcio, "LYRICS", Path(tmp) / "lyrics"), \
             patch.object(lrcio.LY, "_cached", return_value=True), \
             patch.object(lrcio.LY, "get_lrc", return_value={"lrc": raw}), \
             patch.object(lrcio.LY, "audio_duration", return_value=60):
            audio = Path(tmp) / "歌手 - 曲.mp3"
            draft = lrcio.load(audio)
            self.assertTrue(draft["from_cache"])
            self.assertTrue(lrcio.save(audio, draft["lines"])["ok"])
            doc = lrcio.load(audio)
            self.assertEqual([r["text"] for r in doc["lines"]], ["あの日"])
            self.assertTrue(lrcio.store_path(audio).is_file())
            self.assertFalse((Path(tmp) / "歌手 - 曲.lrc").exists())
