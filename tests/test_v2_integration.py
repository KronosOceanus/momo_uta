"""v2 端到端：导入、API 读写、普通播放、改读音、v1 保存转换。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import importing as IMP
import v1_fixtures as V1
from nihonco_player.core import library as LIB
from nihonco_player.core import lrc_doc as D
from nihonco_player.core import lyric_rows as R
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import lyrics_cache as LC
from nihonco_player.core.library import CACHE
from nihonco_player.service import lrc as SVC_LRC
from nihonco_player.service import song as SONG


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

    def test_v1_save_is_converted_to_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            v1 = V1.render_nhlrc(
                [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}], [],
                {0: [["君", "きみ", "A"]], 1: [["花", "はな", "A"]]})
            with patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LC, "CACHE", root / "cache"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
                LRF.store_path(audio).write_text(v1, encoding="utf-8")
                res = SONG.save_lyrics(item, [{"t": 1.0, "text": "君"},
                                              {"t": 2.0, "text": "花"}], "align")
                self.assertTrue(res["ok"], res)
                raw = LRF.store_path(audio).read_text(encoding="utf-8")
                self.assertIn("#NHLRC 2", raw)
                self.assertNotIn("#NHLRC 1", raw)


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
    def test_delete_writes_v2_disabled_and_restore_converts_v1_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            v1 = V1.render_nhlrc([{"t": 1.0, "text": "君"},
                                   {"t": 2.0, "text": "花"}], [],
                                  {0: [["君", "きみ", "A"]],
                                   1: [["花", "はな", "A"]]})
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
                LRF.store_path(audio).write_text(v1, encoding="utf-8")
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

    def test_export_legacy_body_is_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            item = _cache(audio)
            v1 = V1.render_nhlrc([{"t": 1.0, "text": "君"}], [],
                                  {0: [["君", "きみ", "A"]]})
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
                LRF.store_path(audio).write_text(v1, encoding="utf-8")
                out = SVC_LRC.lrc_action({"action": "export", "uid": item["uid"],
                                          "lines": [{"t": 1.0, "text": "君"}]})
                self.assertTrue(out["ok"], out)
                self.assertIn("#NHLRC 2", out["nhlrc"])


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
        from nihonco_player.core import lrc_files as LRF

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
    def test_save_rows_rejects_empty_rows_without_overwrite(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from nihonco_player.core import lrc_files as LRF

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
        from nihonco_player.core import lrc_files as LRF

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
        from nihonco_player.core import lrc_files as LRF
        from nihonco_player.service import lyric_document as LD

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
        from nihonco_player.core import lrc_files as LRF

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
        from nihonco_player.core import lrc_files as LRF

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                line = [{"t": 1.0, "text": "君"}]
                self.assertTrue(LRF.save(audio, line, translations={0: "you"},
                                          trans_lang="en")["ok"])
                self.assertTrue(LRF.save(audio, line)["ok"])
                self.assertEqual(LRF.load_rows(audio)["trans_lang"], "en")
