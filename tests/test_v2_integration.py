"""v2 端到端：导入、API 读写、普通播放、改读音。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import importing as IMP
from momo_player.core import library as LIB
from momo_player.core import lyric_rows as R
from momo_player.core import lrc_files as LRF
from momo_player.core import lyrics_cache as LC
from momo_player.core.library import CACHE
from momo_player.service import lrc as SVC_LRC
from momo_player.service import song as SONG


def _item(audio):
    return {"key": "k", "uid": LRF.uid_of(audio), "file": str(audio),
            "stem": audio.stem, "orig": "曲", "title": "曲",
            "artist": "歌手", "has_lyric": True, "group": ""}


def _cache(audio):
    item = _item(audio)
    CACHE.clear()
    CACHE["0"] = item
    LIB.BY_UID[item["uid"]] = item
    return item


class TestV2Integration(unittest.TestCase):
    def test_import_local_lrc_writes_v2_without_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"
            lrc = root / "歌手 - 曲.lrc"
            audio.touch()
            lrc.write_text("[00:01.00]君\n[00:02.00]花\n[00:03.00]夜\n",
                           encoding="utf-8")
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = IMP.import_paths([str(audio), str(lrc)], with_lrc=True)
                self.assertEqual(len(res["added"]), 1)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", raw)
                doc = LRF.load_rows(audio)
                self.assertEqual(doc["model"], 2)
                self.assertEqual(doc["rows"][0]["kind"], "lyric")
                self.assertTrue(doc["rows"][0]["lid"].startswith("l_"))

    def test_v2_load_save_play_and_edit_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "metadata", "text": "[ar:X]", "t": None},
                {"kind": "lyric", "text": "君", "t": 2.0, "lid": "l_a",
                 "tokens": [], "trans": "你"},
                {"kind": "blank", "text": "", "t": None},
                {"kind": "lyric", "text": "花", "t": 1.0, "lid": "l_b",
                 "tokens": [], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                saved = LRF.save_rows(audio, rows)
                self.assertTrue(saved["ok"], saved)
                load = SVC_LRC.lrc_action({"action": "load", "uid": item["uid"]})
                self.assertEqual(load["model"], 2)
                self.assertEqual([r["kind"] for r in load["rows"]],
                                 ["metadata", "lyric", "blank", "lyric"])
                out = SVC_LRC.lrc_action({
                    "action": "save_rows", "uid": item["uid"],
                    "version": load["version"],
                    "rows": [{**r, "trans": "新译" if r["kind"] == "lyric" else r.get("trans", "")}
                             for r in load["rows"]],
                })
                self.assertTrue(out["ok"], out)
                again = LRF.load_rows(audio)
                self.assertEqual(again["rows"][1]["trans"], "新译")
                payload = SONG.song_payload(item["uid"])
                self.assertEqual([x["text"] for x in payload["lines"]], ["花", "君"])
                self.assertTrue(SONG.edit_line(item["uid"], 0, 0, "はな"))



class TestV2Contract(unittest.TestCase):
    def test_export_rows_is_v2_and_keeps_unsaved_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "你"}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LRF.save_rows(audio, rows)
                self.assertTrue(saved["ok"])
                out = SVC_LRC.lrc_action({
                    "action": "export", "uid": item["uid"],
                    "rows": [{"kind": "lyric", "text": "花", "t": 2.0,
                              "lid": "l_b", "tokens": [], "trans": "花"}]})
                self.assertTrue(out["ok"], out)
                self.assertIn("#NHLRC 2", out["nhlrc"])
                self.assertIn("l_b", out["nhlrc"])
                self.assertTrue(out["lrc"].startswith("[00:02.00]花"))

    def test_save_rows_without_trans_lang_preserves_existing_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "you"}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows, trans_lang="en")["ok"])
                out = SVC_LRC.lrc_action({
                    "action": "save_rows", "uid": item["uid"],
                    "rows": [{**rows[0], "trans": "you!"}]})
                self.assertTrue(out["ok"], out)
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")


class TestV2TokenRepair(unittest.TestCase):
    def test_partial_tokens_keep_reading_after_text_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            rows = [{"kind": "lyric", "text": "君の花", "t": 1.0, "lid": "l_a",
                     "tokens": [
                         {"tid": "t1", "start": 0, "end": 1, "base": "君", "ruby": "きみ", "level": "A"},
                         {"tid": "t2", "start": 1, "end": 2, "base": "の", "ruby": None, "level": "K"},
                     ], "trans": ""}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                item = _item(audio)
                item["file"] = str(audio)
                CACHE.clear(); CACHE["0"] = item; LIB.BY_UID[item["uid"]] = item
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                got = LRF.load_rows(audio)
                self.assertEqual(len(got["rows"][0]["tokens"]), 3)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみ")
                self.assertEqual(got["rows"][0]["tokens"][2]["base"], "花")


class TestV2StalePlaybackEdit(unittest.TestCase):
    def test_lid_relocated_after_playback_order_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_jun",
                 "tokens": [{"tid": "t_j", "start": 0, "end": 1, "base": "君",
                             "ruby": "きみ", "level": "A"}], "trans": ""},
                {"kind": "lyric", "text": "花", "t": 2.0, "lid": "l_hana",
                 "tokens": [{"tid": "t_h", "start": 0, "end": 1, "base": "花",
                             "ruby": "はな", "level": "A"}], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                payload = SONG.song_payload(item["uid"])
                self.assertEqual(payload["lines"][0]["lid"], "l_jun")
                # 文件顺序不变，但播放时间改成 花 在前。
                swapped = [dict(rows[0], t=2.0), dict(rows[1], t=1.0)]
                self.assertTrue(LRF.save_rows(audio, swapped)["ok"])
                out = SONG.edit_line_action({"uid": item["uid"], "line": 0,
                                             "lid": "l_jun", "start": 0,
                                             "reading": "きみだ"})
                self.assertIn("きみだ", out["ruby"])
                got = LRF.load_rows(audio)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみだ")
                self.assertEqual(got["rows"][1]["tokens"][0]["ruby"], "はな")


class TestV2DeletedTarget(unittest.TestCase):
    def test_deleted_lid_is_rejected_not_reassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_jun",
                 "tokens": [{"tid": "t_j", "start": 0, "end": 1, "base": "君",
                             "ruby": "きみ", "level": "A"}], "trans": ""},
                {"kind": "lyric", "text": "花", "t": 2.0, "lid": "l_hana",
                 "tokens": [{"tid": "t_h", "start": 0, "end": 1, "base": "花",
                             "ruby": "はな", "level": "A"}], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                # 删掉「君」，旧页面仍拿 l_jun 提交。
                self.assertTrue(LRF.save_rows(audio, [rows[1]])["ok"])
                out = SONG.edit_line_action({"uid": item["uid"], "line": 0,
                                             "lid": "l_jun", "start": 0,
                                             "reading": "くん"})
                self.assertFalse(out.get("ok", True), out)
                got = LRF.load_rows(audio)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "はな")


class TestV2ResetAndLanguage(unittest.TestCase):
    def test_reset_keeps_metadata_before_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "metadata", "text": "[ar:X]", "t": None},
                {"kind": "blank", "text": "", "t": None},
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                 "tokens": [], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                out = SONG.save_lyrics(item, None, "reset")
                self.assertTrue(out["ok"], out)
                got = LRF.load_rows(audio)["rows"]
                self.assertEqual([r["kind"] for r in got],
                                 ["metadata", "blank", "lyric"])
                self.assertEqual(got[0]["text"], "[ar:X]")

    def test_replace_import_preserves_trans_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            v2 = R.render_rows([{"kind": "lyric", "text": "君", "t": 1.0,
                                 "lid": "l_a", "tokens": [], "trans": "you"}],
                               trans_lang="en")
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                out = SONG.save_lyrics(item, mode="replace", text=v2)
                self.assertTrue(out["ok"], out)
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")


class TestV2VersionRace(unittest.TestCase):
    def test_stale_version_after_reorder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            rows = [
                {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_jun",
                 "tokens": [{"tid": "t_j", "start": 0, "end": 1, "base": "君",
                             "ruby": "きみ", "level": "A"}], "trans": ""},
                {"kind": "lyric", "text": "花", "t": 2.0, "lid": "l_hana",
                 "tokens": [{"tid": "t_h", "start": 0, "end": 1, "base": "花",
                             "ruby": "はな", "level": "A"}], "trans": ""},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"):
                first = LRF.save_rows(audio, rows)
                old = first["version"]
                LRF.save_rows(audio, [dict(rows[0], t=3.0), dict(rows[1], t=0.5)])
                out = SONG.edit_line_action({"uid": item["uid"], "line": 0,
                                             "lid": "l_jun", "start": 0,
                                             "reading": "くん", "version": old})
                self.assertFalse(out.get("ok", True), out)
                got = LRF.load_rows(audio)
                self.assertEqual(got["rows"][0]["tokens"][0]["ruby"], "きみ")


class TestV2DisabledAndRestore(unittest.TestCase):
    def test_delete_and_restore_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": ""},
                    {"kind": "lyric", "text": "花", "t": 2.0, "lid": "l_b",
                     "tokens": [], "trans": ""}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                self.assertTrue(LRF.delete_store(audio)["ok"])
                disabled = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", disabled)
                self.assertTrue(LRF.restore_backup(audio)["ok"])
                restored = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", restored)
                self.assertNotIn("#NHLRC 1", restored)


class TestV2StaleFallback(unittest.TestCase):
    def test_text_changed_same_lid_with_old_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            old = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                    "tokens": [], "trans": ""}]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                first = LRF.save_rows(audio, old)
                LRF.save_rows(audio, [{"kind": "lyric", "text": "僕", "t": 1.0,
                                       "lid": "l_a", "tokens": [], "trans": ""}])
                out = SONG.edit_line_action({"uid": item["uid"], "line": 0,
                                             "lid": "l_a", "start": 0,
                                             "reading": "きみだ",
                                             "version": first["version"]})
                self.assertFalse(out.get("ok", True), out)
                self.assertEqual(LRF.load_rows(audio)["rows"][0]["text"], "僕")



class TestV2TrailingSpace(unittest.TestCase):
    def test_trailing_space_keeps_lid_tokens_and_trans(self):
        rows = [{"kind": "lyric", "text": "君 ", "t": 1.0, "lid": "l_a",
                 "tokens": [{"tid": "t1", "start": 0, "end": 1,
                             "base": "君", "ruby": "きみ", "level": "A"}],
                 "trans": "你"}]
        got = R.parse_rows(R.render_rows(rows))
        self.assertEqual(got[0]["text"], "君 ")
        self.assertEqual(got[0]["lid"], "l_a")
        self.assertEqual(got[0]["tokens"][0]["tid"], "t1")
        self.assertEqual(got[0]["trans"], "你")


class TestV2LegacyExportMetadata(unittest.TestCase):
    def test_cache_export_keeps_metadata_after_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            text = "\n[ar:X]\n[00:01.00]君\n"
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
                LRF.store_path(audio).write_text(text, encoding="utf-8")
                out = SVC_LRC.lrc_action({
                    "action": "export", "uid": item["uid"],
                    "lines": [{"t": None, "text": ""},
                              {"t": 1.0, "text": "君"}]})
                self.assertTrue(out["ok"], out)
                self.assertTrue(out["nhlrc"].startswith("\n[ar:X]"), out["nhlrc"])


class TestV2CoreTransLang(unittest.TestCase):
    def test_core_save_rows_inherits_existing_trans_lang(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, [
                    {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "you"}], trans_lang="en")["ok"])
                self.assertTrue(LRF.save_rows(audio, [
                    {"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                     "tokens": [], "trans": "you!"}])["ok"])
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")


class TestV2EmptyRows(unittest.TestCase):
    def test_blank_only_is_skipped_without_file(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                out = LRF.save_rows(audio, [{"kind": "blank", "text": "",
                                             "t": None}])
                self.assertTrue(out["ok"])
                self.assertTrue(out["skipped"])
                self.assertFalse(LRF.store_path(audio).exists())

    def test_save_rows_rejects_empty_rows_without_overwrite(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                rows = [{"kind": "lyric", "text": "君", "t": 1.0, "lid": "l_a",
                         "tokens": [], "trans": ""}]
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                before = LRF.store_path(audio).read_text(encoding="utf-8")
                out = LRF.save_rows(audio, [])
                self.assertFalse(out["ok"])
                self.assertEqual(LRF.store_path(audio).read_text(encoding="utf-8"), before)


class TestV2BlankOnlyDocument(unittest.TestCase):
    def test_blank_and_metadata_only_document_is_legal(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            rows = [
                {"kind": "metadata", "text": "[ar:X]", "t": None},
                {"kind": "blank", "text": "", "t": None},
            ]
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.save_rows(audio, rows)["ok"])
                got = LRF.load_rows(audio)["rows"]
                self.assertEqual([r["kind"] for r in got], ["metadata", "blank"])


class TestV2DisabledPlayback(unittest.TestCase):
    def test_disabled_rows_and_playback_are_explicit(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF
        from momo_player.service import lyric_document as LD

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertTrue(LRF.delete_store(audio)["ok"])
                loaded = LD.load_rows(item["uid"])
                self.assertTrue(loaded["disabled"])
                played = LD.playback(item["uid"])
                self.assertTrue(played.get("disabled"))
                self.assertEqual(played["lines"], [])


class TestV2LegacyExportRows(unittest.TestCase):
    def test_added_body_rows_survive_rows_from_legacy(self):
        from momo_player.core import lrc_files as LRF

        doc = {
            "text": "[00:01.00]a\n[00:02.00]b\n",
            "body_rows": [{"t": 1.0, "text": "a"}, {"t": 2.0, "text": "b"}],
        }
        lines = [{"t": 1.0, "text": "a"}, {"t": 2.0, "text": "b"},
                 {"t": 3.0, "text": "c"}]
        rows = LRF.rows_from_legacy(doc, lines)
        self.assertEqual([r["text"] for r in rows], ["a", "b", "c"])
        self.assertEqual(rows[2]["kind"], "lyric")
        self.assertTrue(rows[2]["lid"])


class TestV2LegacySaveTransLang(unittest.TestCase):
    def test_old_save_inherits_existing_trans_lang(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                line = [{"t": 1.0, "text": "君"}]
                self.assertTrue(LRF.save(audio, line, translations={0: "you"},
                                          trans_lang="en")["ok"])
                self.assertTrue(LRF.save(audio, line, translations={0: "you"})["ok"])
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")


class TestV2ExportRows(unittest.TestCase):
    def test_export_rows_prefers_explicit_rows(self):
        from momo_player.core import lrc_files as LRF

        doc = {"text": "[00:01.00]a\n", "body_rows": [{"t": 1.0, "text": "a"}]}
        rows = [{"kind": "lyric", "text": "x", "t": 1.0, "lid": "l_x", "tokens": []}]
        self.assertEqual(LRF.export_rows(doc, rows=rows), rows)

    def test_export_rows_accepts_kind_rows_in_lines(self):
        from momo_player.core import lrc_files as LRF

        doc = {"text": "", "body_rows": []}
        rows = [{"kind": "lyric", "text": "x", "t": 1.0, "lid": "l_x", "tokens": []}]
        self.assertEqual(LRF.export_rows(doc, lines=rows), rows)


class TestV2LegacyExportDeletion(unittest.TestCase):
    def test_deleted_body_rows_are_removed(self):
        from momo_player.core import lrc_files as LRF

        doc = {"text": "[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n",
               "body_rows": [{"t": 1.0, "text": "a"}, {"t": 2.0, "text": "b"},
                             {"t": 3.0, "text": "c"}]}
        rows = LRF.rows_from_legacy(doc, [{"t": 1.0, "text": "a"},
                                          {"t": 2.0, "text": "b"}])
        self.assertEqual([r["text"] for r in rows], ["a", "b"])

    def test_empty_save_lines_rejected(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                self.assertFalse(LRF.save(audio, [])["ok"])

    def test_doc_from_rows_keeps_trans_lang(self):
        from momo_player.core import lrc_files as LRF

        doc = LRF.doc_from_rows(
            [{"kind": "lyric", "text": "a", "t": 1.0, "lid": "l_x",
              "tokens": [], "trans": "x"}], trans_lang="en")
        self.assertEqual(doc["trans_lang"], "en")


class TestV2SaveRowIds(unittest.TestCase):
    def test_save_rows_returns_server_generated_ids(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                saved = LRF.save_rows(audio, [
                    {"kind": "lyric", "text": "君", "t": 1.0, "tokens": [],
                     "trans": ""}])
                self.assertTrue(saved["ok"])
                self.assertEqual(saved["ids"][0]["text"], "君")
                self.assertTrue(saved["ids"][0]["lid"])
                loaded = LRF.load_rows(audio)
                self.assertEqual(loaded["rows"][0]["lid"], saved["ids"][0]["lid"])


class TestV2SaveFillsTokens(unittest.TestCase):
    def test_save_rows_fills_empty_tokens(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from momo_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                LRF.save_rows(audio, [{"kind": "lyric", "text": "君の名前",
                                       "t": 1.0, "lid": "l_a", "tokens": []}])
                got = LRF.load_rows(audio)
                self.assertTrue(got["rows"][0]["tokens"])


class TestV2PlainLrcPlan(unittest.TestCase):
    def test_plain_lrc_import_generates_tokens(self):
        from momo_player.core import lrc_files as LRF

        rows = LRF.plain_lrc_rows("[00:01.00]君の名前\n")
        self.assertTrue(rows[0]["tokens"])
        self.assertTrue(any(t.get("ruby") for t in rows[0]["tokens"]))

    def test_plain_lrc_drops_only_out_of_order_empty_timed_rows(self):
        from momo_player.core import lrc_files as LRF

        rows = LRF.plain_lrc_rows(
            "[00:01.00]A\n[00:00.90]\n[00:02.00]B\n")
        self.assertEqual([(r["t"], r["text"]) for r in rows],
                         [(1.0, "A"), (2.0, "B")])

        rows = LRF.plain_lrc_rows(
            "[00:01.00]A\n[00:01.10]\n[00:02.00]B\n")
        self.assertEqual([(r["t"], r["text"]) for r in rows],
                         [(1.0, "A"), (1.1, ""), (2.0, "B")])

        rows = LRF.plain_lrc_rows(
            "[00:01.00]A\n\n[00:02.00]B\n")
        self.assertEqual([(r["t"], r["text"]) for r in rows],
                         [(1.0, "A"), (None, ""), (2.0, "B")])
