"""歌词存储：data/lyrics、旧文件迁移、手改读音并入 nhlrc、按内容对齐。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import library as LIB
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
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), ann)
                self.assertTrue(LRF.store_path(audio).is_file())
                doc = LRF.load(audio)
            self.assertEqual(doc["kind"], "nhlrc")
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


class TestManualReading(unittest.TestCase):
    def _env(self, root):
        audio = root / "歌手 - 曲.mp3"
        audio.touch()
        CACHE.clear()
        it = {"key": "k1", "uid": LRF.uid_of(audio), "file": str(audio),
              "stem": audio.stem, "orig": "曲", "title": "曲",
              "artist": "歌手", "has_lyric": True, "group": ""}
        CACHE["0"] = it
        LIB.BY_UID[it["uid"]] = it
        return audio

    def test_edit_reading_writes_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})                # 先有正文
                SONG.song_payload(LRF.uid_of(audio))                       # 自动注音并落盘
                res = SONG.edit_line_action({"uid": LRF.uid_of(audio), "line": 0,
                                             "start": 0, "reading": "きみだ"})
                self.assertIn("きみだ", res["ruby"])
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("きみだ", raw)
                doc = LRF.load(audio)
                self.assertEqual("".join(x[0] for x in doc["annotations"][0]), "君の名前")

    def test_editing_line_preserves_unmodified_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                SONG.song_payload(LRF.uid_of(audio))
                uid = LRF.uid_of(audio)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみだ"})
                item = CACHE["0"]
                lines = [{"t": 5.0, "text": "君の名", "trans": ""},
                         {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                         {"t": 13.0, "text": "また会おう", "trans": ""}]
                res = SONG.save_lyrics(item, lines, "align")
                self.assertTrue(res.get("ok"), res)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("きみだ", raw)

    def test_save_preserves_ids_for_unchanged_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                uid = LRF.uid_of(audio)
                SONG.song_payload(uid)
                SONG.save_lyrics(CACHE["0"], rows(), "align")
                before = LRF.load(audio, uid)
                SONG.save_lyrics(CACHE["0"], rows(), "align")
                after = LRF.load(audio, uid)
                self.assertEqual(before["line_ids"], after["line_ids"])
                self.assertEqual(before["token_ids"], after["token_ids"])

    def test_save_keeps_lid_but_renews_tids_when_text_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                uid = LRF.uid_of(audio)
                SONG.song_payload(uid)
                SONG.save_lyrics(CACHE["0"], rows(), "align")
                before = LRF.load(audio, uid)
                lines = [{"t": 5.0, "text": "君の名"}, {"t": 9.0, "text": "呼んでくれた"},
                         {"t": 13.0, "text": "また会おう"}]
                SONG.save_lyrics(CACHE["0"], lines, "align")
                after = LRF.load(audio, uid)
                self.assertEqual(before["line_ids"][0], after["line_ids"][0])
                self.assertNotEqual(before["token_ids"][0], after["token_ids"][0])

    def test_lrc_load_exposes_lid_and_token_spans(self):
        from nihonco_player.service import lrc as SVC_LRC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                uid = LRF.uid_of(audio)
                SONG.song_payload(uid)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみだ"})
                doc = SVC_LRC.lrc_action({"action": "load", "uid": uid})
                row = doc["lines"][0]
                self.assertTrue(row["lid"].startswith("l_"))
                self.assertEqual([t["base"] for t in row["tokens"]][0], "君")
                self.assertEqual(row["tokens"][0]["ruby"], "きみだ")
                self.assertEqual(row["tokens"][-1]["end"], len(row["text"]))

    def test_save_with_tid_payload_keeps_edited_line_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                uid = LRF.uid_of(audio)
                SONG.song_payload(uid)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみだ"})
                before = LRF.load(audio, uid)
                tokens = []
                pos = 0
                for ti, seg in enumerate(before["annotations"][0]):
                    base = seg[0]
                    end = pos + len(base)
                    if ti < 2:
                        tokens.append({"tid": before["token_ids"][0][ti],
                                       "start": pos, "end": end, "base": base})
                    pos = end
                lines = [
                    {"t": 5.0, "text": "君の名", "trans": "",
                     "lid": before["line_ids"][0], "tokens": tokens},
                    {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                    {"t": 13.0, "text": "また会おう", "trans": ""},
                ]
                res = SONG.save_lyrics(CACHE["0"], lines, "align")
                self.assertTrue(res.get("ok"), res)
                after = LRF.load(audio, uid)
                self.assertIn("きみだ", LRF.store_path(audio).read_text(encoding="utf-8"))
                self.assertEqual(after["line_ids"][0], before["line_ids"][0])
                self.assertEqual(after["token_ids"][0][0], before["token_ids"][0][0])
                self.assertNotEqual(after["token_ids"][0][-1], before["token_ids"][0][-1])

    def test_edit_clear_resets_to_engine_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            from nihonco_player.core import playlists as PL
            from nihonco_player.service import playlist as SVC_PL
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(PL, "FILE", root / "playlists.json"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                SONG.song_payload(LRF.uid_of(audio))
                SONG.edit_line_action({"uid": LRF.uid_of(audio), "line": 0,
                                       "start": 0, "reading": "きみだ"})
                self.assertIn("きみだ", LRF.store_path(audio).read_text(encoding="utf-8"))
                SVC_PL.playlists_action({"action": "edit_clear", "uid": LRF.uid_of(audio)})
                SONG.song_payload(LRF.uid_of(audio))                     # 重新注音并落盘
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertNotIn("きみだ", raw)


class TestSaveAlignment(unittest.TestCase):
    def test_insert_line_keeps_other_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear()
            it = {"key": "k2", "uid": LRF.uid_of(audio), "file": str(audio),
              "stem": audio.stem, "orig": "曲", "title": "曲",
              "artist": "歌手", "has_lyric": True, "group": ""}
            CACHE["0"] = it
            LIB.BY_UID[it["uid"]] = it
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                seed = {0: [["君", "きみ", "A"], ["の名前", None, None]],
                        1: [["呼んで", None, None], ["くれた", None, None]]}
                LRF.save(audio, rows()[:2], seed)
                before = LRF.load(audio)["annotations"]
                from nihonco_player.service import lrc as SVC
                res = SVC.lrc_action({"action": "save", "uid": LRF.uid_of(audio), "lines": [
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


class TestDeleteStore(unittest.TestCase):
    def test_delete_writes_disabled_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                LRF.save(audio, rows()[:2], {})       # 第二次保存生成 .bak
                store = LRF.store_path(audio)
                bak = LRF.store_backup(audio)
                self.assertTrue(store.is_file() and bak.is_file())
                res = LRF.delete_store(audio)
                self.assertTrue(res["ok"])
                self.assertTrue(store.is_file())       # disabled 文档仍在
                self.assertTrue(bak.is_file())         # 备份保留，可恢复
                doc = LRF.load(audio)
                self.assertTrue(doc["disabled"])
                self.assertEqual(doc["lines"], [])


class TestSharedLyricsSource(unittest.TestCase):
    def test_store_only_is_not_pending_and_lrc_sees_same(self):
        from nihonco_player.service import lrc as SVC_LRC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            audio.touch()
            CACHE.clear()
            it = {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
                  "stem": audio.stem, "orig": "曲", "title": "曲",
                  "artist": "歌手", "has_lyric": False, "group": ""}
            CACHE["0"] = it
            LIB.BY_UID[it["uid"]] = it
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows(), {})
                payload = SONG.song_payload(LRF.uid_of(audio))
                lrc = SVC_LRC.lrc_action({"action": "load", "uid": LRF.uid_of(audio)})
            self.assertFalse(payload.get("pending"))
            self.assertEqual(len(payload["lines"]), 3)
            self.assertTrue(CACHE["0"]["has_lyric"])
            self.assertFalse(lrc["pending"])
            self.assertEqual([x["text"] for x in lrc["lines"]],
                             [x["text"] for x in rows()])


if __name__ == "__main__":
    unittest.main()
