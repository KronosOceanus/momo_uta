"""权威歌词写入边界：nhlrc 只由用户动作写，缓存只读回退。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import importing as IMP
from nihonco_player.core import library as LIB
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import lyrics as LY
from nihonco_player.core import lyrics_cache as LC
from nihonco_player.core.library import CACHE
from nihonco_player.service import song as SONG


def rows():
    return [{"t": 1.0, "text": "君の名前"}, {"t": 5.0, "text": "呼んでくれた"}]


def seed_cache(text):
    p = LC.cache_path("曲", "歌手")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"lrc": text, "title": "曲", "artist_q": "歌手"}),
                 encoding="utf-8")


class TestAuthority(unittest.TestCase):
    def _env(self, root):
        audio = root / "歌手 - 曲.mp3"
        audio.touch()
        it = {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
              "stem": audio.stem, "orig": "曲", "title": "曲", "artist": "歌手",
              "has_lyric": True, "group": ""}
        CACHE.clear(); CACHE["0"] = it
        LIB.BY_UID.clear(); LIB.BY_UID[it["uid"]] = it
        return audio, it

    def test_opening_cached_lyrics_does_not_write_nhlrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, it = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                seed_cache("[00:01.00]君の名前\n[00:05.00]呼んでくれた\n[00:09.00]また会おう\n")
                d = SONG.song_payload(it["uid"])
                self.assertGreaterEqual(len(d["lines"]), 2)
                self.assertFalse(LRF.store_path(audio).exists())

    def test_delete_writes_disabled_and_skips_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, it = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                seed_cache("[00:01.00]君の名前\n[00:05.00]呼んでくれた\n[00:09.00]また会おう\n")
                LRF.save(audio, rows(), {})
                res = LRF.delete_store(audio)
                self.assertTrue(res["ok"])
                doc = LRF.load(audio)
                self.assertTrue(doc["disabled"])
                self.assertEqual(doc["lines"], [])
                d = SONG.song_payload(it["uid"])
                self.assertTrue(d["disabled"])
                self.assertFalse(d["pending"])

                # 保存新歌词可重新启用
                LRF.save(audio, rows(), {})
                self.assertFalse(LRF.load(audio)["disabled"])

    def test_expected_version_blocks_stale_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                first = LRF.save(audio, rows(), {})
                old = first["version"]
                second = LRF.save(audio, [{"t": 2.0, "text": "新版"}], {})
                self.assertNotEqual(second["version"], old)
                stale = LRF.save(audio, rows(), {}, expected_version=old)
                self.assertFalse(stale["ok"])
                self.assertTrue(stale["conflict"])

    def test_save_does_not_write_shared_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                self.assertFalse((root / "cache").exists())

    def test_save_is_atomic_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                self.assertTrue(LRF.store_path(audio).is_file())
                self.assertEqual(list((root / "lyrics").glob(".*tmp*")), [])

    def test_restore_reenables_disabled_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                self.assertTrue(LRF.delete_store(audio)["ok"])
                self.assertTrue(LRF.load(audio)["disabled"])
                self.assertTrue(LRF.restore_backup(audio)["ok"])
                doc = LRF.load(audio)
                self.assertFalse(doc["disabled"])
                self.assertEqual(len(doc["lines"]), 2)

    def test_disabled_skips_lazy_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, it = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LY, "get_lrc") as get_lrc:
                LRF.delete_store(audio)
                SONG.lazy_match(it)
            self.assertFalse(get_lrc.called)

    def test_none_version_blocks_old_draft_after_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                old = LRF.load(audio)["version"]
                self.assertEqual(old, "none")
                self.assertTrue(LRF.delete_store(audio, expected_version=old)["ok"])
                stale = LRF.save(audio, rows(), {}, expected_version=old)
                self.assertFalse(stale["ok"])
                self.assertTrue(stale["conflict"])
                self.assertTrue(LRF.load(audio)["disabled"])

    def test_disabled_is_not_a_restorable_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, _ = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.delete_store(audio)                 # 无旧歌词，写 disabled
                self.assertTrue(LRF.save(audio, rows(), {})["ok"])
                self.assertFalse(LRF.backup_path(audio).exists())
                r = LRF.restore_backup(audio)
                self.assertFalse(r["ok"])
                self.assertFalse(r["ok"])

    def test_refresh_failure_is_not_save_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, it = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LIB, "refresh", side_effect=RuntimeError("index down")):
                res = SONG.save_lyrics(it, rows(), "annotated", {0: [["君", "きみ", "A"]]})
                self.assertTrue(res["ok"])
                self.assertFalse(res["refresh_ok"])
                self.assertTrue(LRF.store_path(audio).is_file())

    def test_import_writes_nhlrc_not_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"; audio.touch()
            (root / "歌手 - 曲.lrc").write_text(
                "[00:01.00]君の名前\n[00:05.00]呼んでくれた\n[00:09.00]また会おう\n", encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = IMP.import_paths([str(audio), str(root / "歌手 - 曲.lrc")],
                                       with_lrc=True)
                self.assertEqual(len(res["added"]), 1)
                self.assertTrue(LRF.store_path(audio).is_file())
                self.assertEqual(LRF.load(audio)["lines"][0]["text"], "君の名前")
                self.assertFalse(LC.cache_path("曲", "歌手").exists())


if __name__ == "__main__":
    unittest.main()
