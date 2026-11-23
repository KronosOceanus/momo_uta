"""单行注音缓存：命中、stored 变化、版本变化和损坏回退。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import annotation as A
from momo_player.core import annotation_cache as AC


def fields(text, stored=None):
    return {"ruby": f"<b>{text}</b>", "rm": "r", "ky": "k", "rmH": "rh", "kyH": "kh"}


class TestAnnotationCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.p1 = patch.object(AC, "CACHE_DIR", self.root)
        self.p2 = patch.object(A, "line_fields", side_effect=fields)
        self.p1.start(); self.p2.start(); AC.clear_memory()

    def tearDown(self):
        AC.clear_memory(); self.p2.stop(); self.p1.stop(); self.tmp.cleanup()

    def test_disk_hit_skips_annotation(self):
        a = AC.line_fields("君の名前")
        b = AC.line_fields("君の名前")
        self.assertEqual(a, b)
        self.assertEqual(A.line_fields.call_count, 1)
        self.assertEqual(list(self.root.glob("*.json")), [self.root / (AC._key("君の名前", None) + ".json")])
        # 清内存后仍命中磁盘
        AC.clear_memory()
        c = AC.line_fields("君の名前")
        self.assertEqual(c, a)
        self.assertEqual(A.line_fields.call_count, 1)

    def test_stored_readings_change_key(self):
        AC.line_fields("君", None)
        AC.line_fields("君", [["君", "きみ", "A"]])
        self.assertEqual(A.line_fields.call_count, 2)

    def test_cache_version_invalidates(self):
        AC.line_fields("君")
        with patch.object(AC, "VERSION", 2):
            AC.clear_memory()
            AC.line_fields("君")
        self.assertEqual(A.line_fields.call_count, 2)

    def test_corrupt_cache_recomputes(self):
        AC.line_fields("君")
        p = next(self.root.glob("*.json"))
        p.write_text("{bad", encoding="utf-8")
        AC.clear_memory()
        self.assertEqual(AC.line_fields("君")["ruby"], "<b>君</b>")
        self.assertEqual(A.line_fields.call_count, 2)

    def test_empty_line_does_not_call_annotator(self):
        self.assertEqual(AC.line_fields(""), {})
        self.assertEqual(A.line_fields.call_count, 0)


if __name__ == "__main__":
    unittest.main()
