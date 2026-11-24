"""歌词存储：data/lyrics、旧文件迁移、手改读音并入 nhlrc、按内容对齐。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import library as LIB
from momo_player.core import lrc_files as LRF
from momo_player.core import lyrics_cache as LC
from momo_player.core.library import CACHE
from momo_player.service import song as SONG


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
                lines = [{"t": 5.0, "text": "君の名", "trans": ""},
                         {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                         {"t": 13.0, "text": "また会おう", "trans": ""}]
                item = CACHE["0"]
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
        from momo_player.service import lrc as SVC_LRC
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
                self.assertEqual(row["tokens"][0]["level"], "A")
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
                self.assertTrue(res.get("ids"))
                self.assertEqual(res["ids"][0]["text"], "君の名")
                self.assertTrue(res["ids"][0]["lid"].startswith("l_"))
                self.assertTrue(res["ids"][0]["tokens"])
                self.assertEqual(res["ids"][0]["tokens"][0]["ruby"], "きみだ")
                self.assertEqual(res["ids"][0]["tokens"][0]["level"], "A")
                after = LRF.load(audio, uid)
                self.assertIn("きみだ", LRF.store_path(audio).read_text(encoding="utf-8"))
                self.assertEqual(after["line_ids"][0], before["line_ids"][0])
                self.assertEqual(after["token_ids"][0][0], before["token_ids"][0][0])
                self.assertNotEqual(after["token_ids"][0][-1], before["token_ids"][0][-1])

    def test_split_line_keeps_token_readings(self):
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

                def toks(i, start=0, end=None):
                    out, pos = [], 0
                    for ti, seg in enumerate(before["annotations"][i]):
                        e = pos + len(seg[0])
                        if pos >= start and e <= (end if end is not None else len(before["lines"][i]["text"])):
                            out.append({"tid": before["token_ids"][i][ti],
                                        "start": pos - start, "end": e - start,
                                        "base": seg[0]})
                        pos = e
                    return out

                lines = [
                    {"t": 5.0, "text": "君の", "trans": "",
                     "lid": before["line_ids"][0], "tokens": toks(0, 0, 2)},
                    {"t": 5.0, "text": "名前", "trans": "", "tokens": toks(0, 2)},
                    {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                    {"t": 13.0, "text": "また会おう", "trans": ""},
                ]
                res = SONG.save_lyrics(CACHE["0"], lines, "align")
                self.assertTrue(res.get("ok"), res)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("きみだ", raw)
                after = LRF.load(audio, uid)
                self.assertEqual(len(after["lines"]), 4)
                self.assertEqual(after["line_ids"][0], before["line_ids"][0])
                self.assertNotEqual(after["line_ids"][1], before["line_ids"][0])

    def test_blank_line_keeps_following_annotation_index(self):
        from momo_player.service import lrc as SVC_LRC
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
                lines = [{"t": 5.0, "text": "君の名前", "trans": "",
                          "lid": before["line_ids"][0],
                          "tokens": [{"tid": before["token_ids"][0][i],
                                      "start": sum(len(x[0]) for x in before["annotations"][0][:i]),
                                      "end": sum(len(x[0]) for x in before["annotations"][0][:i]) + len(before["annotations"][0][i][0]),
                                      "base": before["annotations"][0][i][0]}
                                     for i in range(len(before["annotations"][0]))]},
                         {"t": None, "text": "", "trans": ""},
                         {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                         {"t": 13.0, "text": "また会おう", "trans": ""}]
                res = SONG.save_lyrics(CACHE["0"], lines, "align")
                self.assertTrue(res.get("ok"), res)
                doc = SVC_LRC.lrc_action({"action": "load", "uid": uid})
                self.assertEqual([x["text"] for x in doc["lines"]],
                                 ["君の名前", "", "呼んでくれた", "また会おう"])
                # 空行不占 annotation i：下面三行仍能读出自己的读音
                self.assertEqual(len(doc["annotations"]), 3)
                self.assertEqual("".join(x[0] for x in doc["annotations"][1]), "呼んでくれた")

    def test_api_save_reload_keeps_token_identity(self):
        from momo_player.service import lrc as SVC_LRC
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
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみだ"})
                before = LRF.load(audio, uid)
                tokens = []
                pos = 0
                for ti, seg in enumerate(before["annotations"][0]):
                    end = pos + len(seg[0])
                    if ti < 2:
                        tokens.append({"tid": before["token_ids"][0][ti],
                                       "start": pos, "end": end, "base": seg[0]})
                    pos = end
                lines = [
                    {"t": 5.0, "text": "君の名", "trans": "",
                     "lid": before["line_ids"][0], "tokens": tokens},
                    {"t": 9.0, "text": "呼んでくれた", "trans": ""},
                    {"t": 13.0, "text": "また会おう", "trans": ""},
                ]
                saved = SVC_LRC.lrc_action({"action": "save", "uid": uid,
                                            "lines": lines})
                self.assertTrue(saved.get("ok"), saved)
                loaded = SVC_LRC.lrc_action({"action": "load", "uid": uid})
                row = loaded["lines"][0]
                self.assertEqual(row["text"], "君の名")
                self.assertIn("きみだ", row["tokens"][0]["ruby"])
                self.assertEqual(row["tokens"][0]["tid"],
                                 before["token_ids"][0][0])
                self.assertNotEqual(row["tokens"][-1]["tid"],
                                    before["token_ids"][0][-1])

    def test_translation_body_keyed_survives_first_save_and_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                first = [{"t": 5.0, "text": "君", "trans": "you"},
                         {"t": 9.0, "text": "花", "trans": "flower"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], first, "align")["ok"])
                uid = LRF.uid_of(audio)
                self.assertEqual(LRF.load(audio, uid)["translations"],
                                 {0: "you", 1: "flower"})
                second = [{"t": 4.0, "text": "空", "trans": "sky"},
                          {"t": 4.5, "text": "空", "trans": ""},
                          {"t": 5.0, "text": "君", "trans": "you"},
                          {"t": 9.0, "text": "花", "trans": "flower"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], second, "align")["ok"])
                self.assertEqual(LRF.load(audio, uid)["translations"],
                                 {0: "sky", 2: "you", 3: "flower"})

    def test_translation_explicit_empty_clears_and_missing_preserves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                rows_with = [{"t": 5.0, "text": "君", "trans": "you"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], rows_with, "align")["ok"])
                uid = LRF.uid_of(audio)
                # 显式 {} 是完整快照：清空全部翻译。
                self.assertTrue(SONG.save_lyrics(CACHE["0"], rows_with, "align",
                                                 translations={})["ok"])
                self.assertEqual(LRF.load(audio, uid)["translations"], {})
                # 缺省 translations，且 lines 没有 trans：沿用旧翻译。
                self.assertTrue(SONG.save_lyrics(CACHE["0"], rows_with, "align")["ok"])
                self.assertTrue(SONG.save_lyrics(CACHE["0"],
                                                 [{"t": 5.0, "text": "君"}],
                                                 "align")["ok"])
                self.assertEqual(LRF.load(audio, uid)["translations"], {0: "you"})

    def test_timed_empty_line_translation_does_not_shift(self):
        from momo_player.service import lrc as SVC_LRC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 1.0, "text": "君", "trans": "you"},
                         {"t": 2.0, "text": "", "trans": ""},
                         {"t": 3.0, "text": "花", "trans": "flower"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align")["ok"])
                uid = LRF.uid_of(audio)
                doc = SVC_LRC.lrc_action({"action": "load", "uid": uid})
                self.assertEqual([(x["text"], x["trans"]) for x in doc["lines"]],
                                 [("君", "you"), ("", ""), ("花", "flower")])
                self.assertEqual(doc["translations"], {0: "you", 1: "flower"})

    def test_lrc_action_missing_translations_preserves_but_empty_clears(self):
        from momo_player.service import lrc as SVC_LRC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                rows_with = [{"t": 5.0, "text": "君", "trans": "you"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], rows_with, "align")["ok"])
                uid = LRF.uid_of(audio)
                # lines 不带 trans：缺省，沿用旧翻译。
                no_trans = [{"t": 5.0, "text": "君"}]
                saved = SVC_LRC.lrc_action({"action": "save", "uid": uid,
                                            "lines": no_trans})
                self.assertTrue(saved.get("ok"), saved)
                self.assertEqual(LRF.load(audio, uid)["translations"], {0: "you"})
                # 显式 {}：清空全部。
                saved = SVC_LRC.lrc_action({"action": "save", "uid": uid,
                                            "lines": rows_with,
                                            "translations": {}})
                self.assertTrue(saved.get("ok"), saved)
                self.assertEqual(LRF.load(audio, uid)["translations"], {})

    def test_edit_reading_preserves_translation_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 5.0, "text": "君", "trans": "you"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align",
                                                 trans_lang="en")["ok"])
                uid = LRF.uid_of(audio)
                self.assertEqual(LRF.load(audio, uid)["trans_lang"], "en")
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみ"})
                doc = LRF.load(audio, uid)
                self.assertEqual(doc["trans_lang"], "en")
                self.assertEqual(doc["translations"], {0: "you"})

    def test_swapped_duplicate_lines_follow_lids_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 5.0, "text": "君"}, {"t": 9.0, "text": "君"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align")["ok"])
                uid = LRF.uid_of(audio)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみ"})
                SONG.edit_line_action({"uid": uid, "line": 1, "start": 0,
                                       "reading": "くん"})
                before = LRF.load(audio, uid)
                swapped = [
                    {"t": 9.0, "text": "君", "lid": before["line_ids"][1],
                     "tokens": [{"tid": before["token_ids"][1][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                    {"t": 5.0, "text": "君", "lid": before["line_ids"][0],
                     "tokens": [{"tid": before["token_ids"][0][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                ]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], swapped, "align")["ok"])
                after = LRF.load(audio, uid)
                self.assertEqual(after["annotations"][0][0][1], "くん")
                self.assertEqual(after["annotations"][1][0][1], "きみ")
                self.assertEqual(after["token_ids"][0], [before["token_ids"][1][0]])
                self.assertEqual(after["token_ids"][1], [before["token_ids"][0][0]])
                self.assertEqual(after["line_ids"][0], before["line_ids"][1])
                self.assertEqual(after["line_ids"][1], before["line_ids"][0])

    def test_inserted_duplicate_line_does_not_take_old_token_or_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 5.0, "text": "君"}, {"t": 9.0, "text": "君"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align")["ok"])
                uid = LRF.uid_of(audio)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみ"})
                SONG.edit_line_action({"uid": uid, "line": 1, "start": 0,
                                       "reading": "くん"})
                before = LRF.load(audio, uid)
                mixed = [
                    {"t": 5.0, "text": "君", "lid": before["line_ids"][0],
                     "tokens": [{"tid": before["token_ids"][0][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                    {"t": 7.0, "text": "君"},
                    {"t": 9.0, "text": "君", "lid": before["line_ids"][1],
                     "tokens": [{"tid": before["token_ids"][1][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                ]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], mixed, "align")["ok"])
                after = LRF.load(audio, uid)
                self.assertEqual(after["annotations"][0][0][1], "きみ")
                self.assertEqual(after["annotations"][2][0][1], "くん")
                self.assertNotIn(after["token_ids"][1][0],
                                 before["token_ids"][0] + before["token_ids"][1])

    def test_token_swap_with_same_lid_keeps_readings_and_tids_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 5.0, "text": "君"}, {"t": 9.0, "text": "君"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align")["ok"])
                uid = LRF.uid_of(audio)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみ"})
                SONG.edit_line_action({"uid": uid, "line": 1, "start": 0,
                                       "reading": "くん"})
                before = LRF.load(audio, uid)
                swapped_tokens = [
                    {"t": 5.0, "text": "君", "lid": before["line_ids"][0],
                     "tokens": [{"tid": before["token_ids"][1][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                    {"t": 9.0, "text": "君", "lid": before["line_ids"][1],
                     "tokens": [{"tid": before["token_ids"][0][0], "start": 0,
                                 "end": 1, "base": "君"}]},
                ]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], swapped_tokens, "align")["ok"])
                after = LRF.load(audio, uid)
                self.assertEqual(after["annotations"][0][0][1], "くん")
                self.assertEqual(after["annotations"][1][0][1], "きみ")
                self.assertEqual(after["token_ids"][0], [before["token_ids"][1][0]])
                self.assertEqual(after["token_ids"][1], [before["token_ids"][0][0]])

    def test_no_lid_reorder_different_texts_keeps_readings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 5.0, "text": "君"}, {"t": 9.0, "text": "花"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], lines, "align")["ok"])
                uid = LRF.uid_of(audio)
                SONG.edit_line_action({"uid": uid, "line": 0, "start": 0,
                                       "reading": "きみ"})
                SONG.edit_line_action({"uid": uid, "line": 1, "start": 0,
                                       "reading": "はな"})
                before = LRF.load(audio, uid)
                swapped = [{"t": 9.0, "text": "花"}, {"t": 5.0, "text": "君"}]
                self.assertTrue(SONG.save_lyrics(CACHE["0"], swapped, "align")["ok"])
                after = LRF.load(audio, uid)
                self.assertEqual(after["annotations"][0][0][1], "はな")
                self.assertEqual(after["annotations"][1][0][1], "きみ")
                self.assertEqual(after["line_ids"][0], before["line_ids"][1])
                self.assertEqual(after["line_ids"][1], before["line_ids"][0])

    def test_first_save_preserves_cached_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "get_lrc", return_value={
                     "lrc": "[ar:歌手]\n[ti:曲名]\n[00:01.00]君\n",
                     "source": "test"}):
                doc = LRF.load(audio)
                self.assertEqual(doc["metadata"][0]["text"], "[ar:歌手]")
                self.assertTrue(SONG.save_lyrics(
                    CACHE["0"], doc["body_rows"], "align")["ok"])
                after = LRF.load(audio)
                self.assertEqual([x["text"] for x in after["metadata"]],
                                 ["[ar:歌手]", "[ti:曲名]"])
                self.assertEqual([x["text"] for x in after["lines"]], ["君"])

    def test_export_maps_metadata_around_blank_body_rows(self):
        from momo_player.service import lrc as SVC_LRC
        from momo_player.core import lrc_doc as DOC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                lines = [{"t": 1.0, "text": "君"}, {"t": None, "text": ""},
                         {"t": 3.0, "text": "花"}]
                ann = {0: [["君", "きみ", "A"]], 2: [["花", "はな", "A"]]}
                trans = {0: "you", 2: "flower"}
                meta = [{"before": 0, "text": "[ar:X]"}]
                lids = {0: "l_11111111", 2: "l_22222222"}
                tids = {0: ["t_11111111"], 2: ["t_22222222"]}
                self.assertTrue(LRF.save(audio, lines, ann, trans,
                                         metadata=meta, trans_lang="en",
                                         line_ids=lids, token_ids=tids)["ok"])
                uid = LRF.uid_of(audio)
                res = SVC_LRC.lrc_action({"action": "export", "uid": uid})
                self.assertTrue(res["ok"])
                exported, tail = DOC._split_nhlrc(res["nhlrc"])
                self.assertTrue(exported.startswith("[ar:X]\n[00:01.00]君"))
                self.assertIn("[00:03.00]花", exported)
                self.assertEqual(tail["trans_lang"], "en")
                self.assertEqual([x["text"] for x in tail["trans"]], ["you", "flower"])
                self.assertEqual([x.get("lid") for x in tail["lines"]],
                                 ["l_11111111", "l_22222222"])
                self.assertEqual([x.get("tid") for x in tail["lines"]],
                                 [["t_11111111"], ["t_22222222"]])

    def test_edit_clear_resets_to_engine_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = self._env(root)
            from momo_player.core import playlists as PL
            from momo_player.service import playlist as SVC_PL
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
                from momo_player.service import lrc as SVC
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
        from momo_player.service import lrc as SVC_LRC
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
