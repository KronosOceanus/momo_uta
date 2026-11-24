"""日志轮转：多份保留 + 运行中超过上限自动切。"""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_uta_app import logsetup


class TestLogRotation(unittest.TestCase):
    def test_rotate_keeps_requested_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            log.write_text("current", encoding="utf-8")
            (Path(tmp) / "app.log.1").write_text("one", encoding="utf-8")
            (Path(tmp) / "app.log.4").write_text("old", encoding="utf-8")
            logsetup._rotate_files(log, 3)
            self.assertFalse(log.exists())
            self.assertEqual((Path(tmp) / "app.log.1").read_text(), "current")
            self.assertEqual((Path(tmp) / "app.log.2").read_text(), "one")
            self.assertFalse((Path(tmp) / "app.log.4").exists())

    def test_warning_has_cooldown_and_resets_after_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = logsetup._LogSink(Path(tmp) / "app.log", max_bytes=100, keep=2)
            err = io.StringIO()
            with patch.object(sys, "__stderr__", err):
                sink._warn("first")
                sink._warn("second")
                sink._recovered()
                sink._warn("third")
            self.assertEqual(err.getvalue().count("[log]"), 2)
            sink.close()

    def test_sink_rotates_when_size_limit_is_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            sink = logsetup._LogSink(log, max_bytes=5, keep=2)
            sink.write("123456")
            self.assertTrue((Path(tmp) / "app.log.1").exists())
            self.assertEqual(sink.file.tell(), 0)
            sink.close()
