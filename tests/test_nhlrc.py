"""nhlrc：正文 + 尾部假名标注的读写与校验。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import lrc_files as LRF


def rows():
    return [{"t": 5.0, "text": "君の名前"}, {"t": 9.0, "text": "呼んでくれた"}]


class TestNhlrc(unittest.TestCase):
    def test_roundtrip_body_and_annotations(self):
        ann = {0: [["君", "きみ", "A"], ["の", None, None], ["名前", "なまえ", "B"]],
               1: [["呼んでくれた", None, None]]}
        text = DOC.render_nhlrc(rows(), [], ann)
        self.assertIn("#NHLRC 1", text)
        body, tail = DOC._split_nhlrc(text)
        self.assertTrue(body.startswith("[00:05.00]君の名前"))
        self.assertEqual(DOC.annotations_for(rows(), tail), ann)

    def test_annotation_dropped_when_text_changed(self):
        ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]}
        text = DOC.render_nhlrc(rows(), [], ann)
        _body, tail = DOC._split_nhlrc(text)
        changed = [{"t": 5.0, "text": "君のなまえ"}, {"t": 9.0, "text": "呼んでくれた"}]
        self.assertEqual(DOC.annotations_for(changed, tail), {})

    def test_annotation_dropped_when_bases_do_not_add_up(self):
        text = DOC.render_nhlrc(rows(), [], {0: [["君", "きみ", "A"]]})
        _body, tail = DOC._split_nhlrc(text)
        self.assertEqual(DOC.annotations_for(rows(), tail), {})

    def test_save_writes_nhlrc_and_keeps_body_lrc_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]}
            with patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "write_local_lrc"):
                res = LRF.save(audio, rows(), ann)
            self.assertTrue(res["ok"])
            p = LRF.nhlrc_path(audio)
            self.assertTrue(p.is_file())
            raw = p.read_text(encoding="utf-8")
            self.assertTrue(raw.startswith("[00:05.00]君の名前"))
            self.assertIn("#NHLRC 1", raw)
            doc = LRF.load(audio)
            self.assertEqual(doc["annotations"], ann)
            self.assertEqual(DOC.render_body(rows(), []), "[00:05.00]君の名前\n[00:09.00]呼んでくれた\n")

    def test_legacy_lrc_still_loads_without_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            LRF.lrc_path(audio).write_text("[00:05.00]君の名前\n", encoding="utf-8")
            doc = LRF.load(audio)
            self.assertEqual(doc["kind"], "lrc")
            self.assertEqual(doc["annotations"], {})
            self.assertEqual([r["text"] for r in doc["lines"]], ["君の名前"])

    def test_backup_created_once_from_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            legacy = "[00:05.00]君の名前\n"
            LRF.lrc_path(audio).write_text(legacy, encoding="utf-8")
            with patch.object(LRF.LY, "audio_duration", return_value=60), \
                 patch.object(LRF.LY, "write_local_lrc"):
                LRF.save(audio, rows())
                self.assertEqual(LRF.backup_path(audio).read_text(encoding="utf-8"), legacy)
                p = LRF.nhlrc_path(audio)
                before = p.read_text(encoding="utf-8")
                LRF.save(audio, rows())
                self.assertEqual(LRF.backup_path(audio).read_text(encoding="utf-8"), legacy)
                self.assertTrue(before.startswith("[00:05.00]君の名前"))


if __name__ == "__main__":
    unittest.main()
