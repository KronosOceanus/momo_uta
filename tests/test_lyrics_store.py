"""歌词存储：data/lyrics、旧文件迁移、手改读音并入 nhlrc、按内容对齐。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import edits as ED
from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import lyrics as LY
from nihonco_player.core import lyrics_cache as LC
from nihonco_player.core.library import CACHE
from nihonco_player.service import song as SONG


def rows():
    return [{"t": 5.0, "text": "君の名前"}, {"t": 9.0, "text": "呼んでくれた"},
            {"t": 13.0, "text": "また会おう"}]


class TestStoreLocation(unittest.TestCase):
    def test_save_goes_to_data_lyrics_not_next_to_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            ann = {0: [["君", "きみ", "A"], ["の名前", None, None]]}
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "write_local_lrc"):
                LRF.save(audio, rows(), ann)
                self.assertTrue(LRF.store_path(audio).is_file())
                self.assertFalse(LRF.nhlrc_path(audio).exists())
                doc = LRF.load(audio)
            self.assertEqual(doc["kind"], "nhlrc")
            self.assertEqual(doc["annotations"], ann)

    def test_legacy_sidecar_is_migrated_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            ann = {0: [["君", "きみ", "A"]]}
            LRF.nhlrc_path(audio).write_text(
                DOC.render_nhlrc([{"t": 5.0, "text": "君"}], [], ann), encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "write_local_lrc"):
                doc = LRF.load(audio)
                self.assertTrue(LRF.store_path(audio).is_file())
                self.assertFalse(LRF.nhlrc_path(audio).exists())
            self.assertEqual(doc["annotations"], ann)


class TestNaming(unittest.TestCase):
    def test_readable_name(self):
        n = LRF.store_name("Love Forever", "清水翔太", "766afe81d2df")
        self.assertEqual(n, "Love Forever - 清水翔太.766afe81d2df.nhlrc")

    def test_sanitize_and_fallback(self):
        self.assertEqual(LRF.store_name("A/B: C?", "X*Y", "abc123def456"),
                         "A_B_ C_ - X_Y.abc123def456.nhlrc")
        self.assertEqual(LRF.store_name("", "", "abc123def456"),
                         "untitled.abc123def456.nhlrc")

    def test_truncate_keeps_uid(self):
        n = LRF.store_name("あ" * 200, "A", "abc123def456")
        self.assertTrue(n.endswith(".abc123def456.nhlrc"))
        self.assertLessEqual(len(n.encode("utf-8")), 140)

    def test_find_by_uid_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            uid = LRF.uid_of(audio)
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                (root / "lyrics").mkdir()
                f = root / "lyrics" / f"别的名字.{uid}.nhlrc"
                f.write_text("", encoding="utf-8")
                self.assertEqual(LRF.store_path(audio, uid), f)
                old = root / "lyrics" / f"{uid}.nhlrc"
                f.unlink()
                old.write_text("", encoding="utf-8")
                self.assertEqual(LRF.store_path(audio, uid), old)


class TestAlign(unittest.TestCase):
    def test_insert_keeps_other_annotations(self):
        old = rows()
        ann = {0: [["君の名前", "きみのなまえ", "A"]],
               1: [["呼んでくれた", "よんでくれた", "A"]],
               2: [["また会おう", "またあおう", "A"]]}
        new = [{"t": 1.0, "text": "新しい行"}] + old
        out = DOC.align_annotations(new, ann)
        self.assertNotIn(0, out)
        self.assertEqual(out[1], ann[0])
        self.assertEqual(out[2], ann[1])
        self.assertEqual(out[3], ann[2])

    def test_delete_and_reorder_follow_text(self):
        ann = {0: [["A", "あ", "A"]], 1: [["B", "び", "A"]], 2: [["C", "し", "A"]]}
        out = DOC.align_annotations([{"t": 1.0, "text": "C"}, {"t": 2.0, "text": "A"}], ann)
        self.assertEqual(out[0], ann[2])
        self.assertEqual(out[1], ann[0])
        self.assertNotIn(2, out)

    def test_changed_text_drops_annotation(self):
        ann = {0: [["君の名前", "きみのなまえ", "A"]]}
        out = DOC.align_annotations([{"t": 1.0, "text": "君の名"}], ann)
        self.assertEqual(out, {})


class TestManualReadingFolded(unittest.TestCase):
    def _env(self, tmp):
        root = Path(tmp)
        audio = root / "歌手 - 曲.mp3"
        audio.touch()
        (root / "歌手 - 曲.lrc").write_text(
            "[00:05.00]君の名前\n[00:09.00]呼んでくれた\n[00:13.00]また会おう\n",
            encoding="utf-8")
        CACHE.clear()
        CACHE["0"] = {"key": "k1", "uid": LRF.uid_of(audio), "file": str(audio),
                      "stem": audio.stem, "orig": "曲", "title": "曲",
                      "artist": "歌手", "has_lyric": True, "group": ""}
        return root, audio

    def test_edit_reading_writes_store_without_readings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, audio = self._env(tmp)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                ED.set_file(root / "readings.json")
                SONG.song_payload(0)                       # 首次注音 → 落盘
                res = SONG.edit_line_action({"idx": "0", "line": 0,
                                             "start": 0, "reading": "きみだ"})
                self.assertIn("きみだ", res["ruby"])
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("きみだ", raw)
                self.assertEqual(ED.for_song("k1"), {})   # 不再写 readings
                doc = LRF.load(audio)
                self.assertEqual("".join(x[0] for x in doc["annotations"][0]), "君の名前")

    def test_old_readings_are_migrated_and_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, audio = self._env(tmp)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                ED.set_file(root / "readings.json")
                ED.put("k1", 0, 0, "きみだ")
                SONG.song_payload(0)
                self.assertEqual(ED.for_song("k1"), {})
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("きみだ", raw)


class TestSaveAlignment(unittest.TestCase):
    def test_insert_line_keeps_other_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            (root / "歌手 - 曲.lrc").write_text(
                "[00:05.00]君の名前\n[00:09.00]呼んでくれた\n", encoding="utf-8")
            CACHE.clear()
            CACHE["0"] = {"key": "k2", "uid": LRF.uid_of(audio), "file": str(audio),
                          "stem": audio.stem, "orig": "曲", "title": "曲",
                          "artist": "歌手", "has_lyric": True, "group": ""}
            with patch.object(LRF, "LYRICS", root / "lyrics"),                  patch.object(LC, "CACHE", root / "cache"),                  patch.object(LRF.LY, "audio_duration", return_value=60):
                ED.set_file(root / "readings.json")
                SONG.song_payload(0)
                before = LRF.load(audio)["annotations"]
                from nihonco_player.service import lrc as SVC
                res = SVC.lrc_action({"action": "save", "idx": "0", "lines": [
                    {"t": 1.0, "text": "新しい行"},
                    {"t": 5.0, "text": "君の名前"},
                    {"t": 9.0, "text": "呼んでくれた"},
                ]})
                self.assertTrue(res["ok"])
                after = LRF.load(audio)["annotations"]
            self.assertNotEqual(after[0], before[0])       # 新行是重新注音的
            self.assertEqual("".join(x[0] for x in after[0]), "新しい行")
            self.assertEqual(after[1], before[0])          # 原来的标注跟着行走了
            self.assertEqual(after[2], before[1])


if __name__ == "__main__":
    unittest.main()
