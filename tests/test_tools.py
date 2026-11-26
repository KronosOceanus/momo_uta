import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import tools


class TestTools(unittest.TestCase):
    def test_env_tool_has_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ffmpeg"
            p.write_text("#!/bin/sh\n", encoding="utf-8")
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
            with patch.dict(os.environ, {"MOMO_FFMPEG": str(p)}), \
                 patch.object(tools, "BUNDLE", Path(tmp) / "bundle"), \
                 patch.object(tools.shutil, "which", return_value=None):
                self.assertEqual(tools.find_tool("ffmpeg", "MOMO_FFMPEG"), str(p))

    def test_bundle_bin_is_searched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bundle"
            b = root / "bin"
            b.mkdir(parents=True)
            p = b / "ffmpeg"
            p.write_text("#!/bin/sh\n", encoding="utf-8")
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
            with patch.object(tools, "BUNDLE", root), \
                 patch.object(tools.shutil, "which", return_value=None):
                self.assertEqual(tools.find_tool("ffmpeg"), str(p))


if __name__ == "__main__":
    unittest.main()
