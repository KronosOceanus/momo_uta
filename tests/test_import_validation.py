"""导入前统一校验：空、乱码、有效行数不足都不写 nhlrc。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import lrc_files as LRF


class TestImportValidation(unittest.TestCase):
    def _with_store(self, func):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", root / "lyrics"):
                func(audio)

    def test_empty_and_junk_rejected(self):
        def run(audio):
            for text in ("", "   \n", "随便写点\n没有时间轴\n"):
                r = LRF.import_text(audio, text)
                self.assertFalse(r["ok"])
                self.assertFalse(LRF.store_path(audio).exists())
        self._with_store(run)

    def test_replacement_character_rejected(self):
        def run(audio):
            text = "[00:01.00]君\ufffd\n[00:02.00]の\n[00:03.00]名前\n"
            r = LRF.import_text(audio, text)
            self.assertFalse(r["ok"])
            self.assertIn("UTF-8", r["error"])
        self._with_store(run)

    def test_too_few_timed_lines_rejected(self):
        def run(audio):
            r = LRF.import_text(audio, "[00:01.00]只有一行\n")
            self.assertFalse(r["ok"])
            self.assertIn("不足", r["error"])
        self._with_store(run)

    def test_three_timed_lines_accepted(self):
        def run(audio):
            text = "[00:01.00]君\n[00:02.00]の\n[00:03.00]名前\n"
            r = LRF.import_text(audio, text)
            self.assertTrue(r["ok"])
            self.assertEqual(LRF.load(audio)["lines"][0]["text"], "君")
        self._with_store(run)

    def test_annotated_nhlrc_can_be_short(self):
        def run(audio):
            text = DOC.render_nhlrc([{"t": 1.0, "text": "君"}], [],
                                    {0: [["君", "きみ", "A"]]})
            r = LRF.import_text(audio, text)
            self.assertTrue(r["ok"])
            self.assertIn("#NHLRC", LRF.store_path(audio).read_text(encoding="utf-8"))
        self._with_store(run)

    def test_invalid_import_does_not_overwrite(self):
        def run(audio):
            good = "[00:01.00]君\n[00:02.00]の\n[00:03.00]名前\n"
            self.assertTrue(LRF.import_text(audio, good)["ok"])
            before = LRF.store_path(audio).read_bytes()
            r = LRF.import_text(audio, "bad\n")
            self.assertFalse(r["ok"])
            self.assertEqual(LRF.store_path(audio).read_bytes(), before)
        self._with_store(run)


if __name__ == "__main__":
    unittest.main()
