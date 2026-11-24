"""HTTP 静态文件边界与音频 Range。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.http import static


class TestStaticBoundary(unittest.TestCase):
    def test_normal_static_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x.js").write_text("ok", encoding="utf-8")
            with patch.object(static, "STATIC", root):
                out = static.static_file("/static/x.js")
            self.assertEqual(out[0], "ok")

    def test_absolute_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(static, "STATIC", Path(tmp)):
                self.assertIsNone(static.static_file("/static//etc/hosts"))

    def test_parent_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(static, "STATIC", Path(tmp)):
                self.assertIsNone(static.static_file("/static/../README.md"))

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside-secret.txt"
            outside.write_text("secret", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(outside)
                with patch.object(static, "STATIC", root):
                    self.assertIsNone(static.static_file("/static/link.txt"))
            finally:
                outside.unlink(missing_ok=True)


class TestAudioRange(unittest.TestCase):
    def test_suffix_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.mp3"; p.write_bytes(b"0123456789")
            code, start, end, size, _, crange = static.audio_info(str(p), "bytes=-3")
        self.assertEqual((code, start, end, crange), (206, 7, 9, "bytes 7-9/10"))

    def test_unsatisfiable_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.mp3"; p.write_bytes(b"0123456789")
            for r in ("bytes=8-2", "bytes=99-100", "bytes=0-2,5-6", "bytes=abc"):
                code, _, _, _, _, crange = static.audio_info(str(p), r)
                self.assertEqual(code, 416, r)
                self.assertEqual(crange, "bytes */10", r)

    def test_range_unit_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.mp3"; p.write_bytes(b"0123456789")
            code, start, end, _, _, crange = static.audio_info(str(p), "Bytes=-3")
        self.assertEqual((code, start, end, crange), (206, 7, 9, "bytes 7-9/10"))

    def test_no_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.mp3"; p.write_bytes(b"0123456789")
            code, start, end, _, _, crange = static.audio_info(str(p), None)
        self.assertEqual((code, start, end, crange), (200, 0, 9, None))
