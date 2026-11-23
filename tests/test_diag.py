"""诊断日志：写不进去也不能抛。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import diag


class TestDiag(unittest.TestCase):
    def test_appends_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(diag, "LOG", Path(tmp) / "app.log"):
                diag.log("t", "hello")
                diag.log("t", "world")
            text = (Path(tmp) / "app.log").read_text(encoding="utf-8")
            self.assertEqual(len(text.strip().splitlines()), 2)
            self.assertIn("hello", text)

    def test_failure_does_not_raise(self):
        with patch.object(diag, "LOG", Path("/dev/null/nope/app.log")):
            diag.log("t", "x")          # 不应抛

    def test_exception_writes_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "app.log"
            with patch.object(diag, "LOG", log):
                try:
                    raise ValueError("坏了")
                except ValueError as e:
                    diag.exception("test", e, path="/api/x")
            text = log.read_text(encoding="utf-8")
            self.assertIn("ValueError", text)
            self.assertIn("Traceback", text)
            self.assertIn("path='/api/x'", text)


if __name__ == "__main__":
    unittest.main()
