"""日志轮转：多份保留 + 运行中超过上限自动切。"""
import tempfile
import unittest
from pathlib import Path

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

    def test_sink_rotates_when_size_limit_is_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            sink = logsetup._LogSink(log, max_bytes=5, keep=2)
            sink.write("123456")
            self.assertTrue((Path(tmp) / "app.log.1").exists())
            self.assertEqual(sink.file.tell(), 0)
            sink.close()
