"""诊断日志：写不进去也不能抛。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import diag


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


if __name__ == "__main__":
    unittest.main()
