"""曲库索引：全量扫描裁剪失效路径。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import fingerprint as FP
from nihonco_player.core import library as LIB
from nihonco_player.core import lrc_files as LRF
from nihonco_player.core import library_index as LI
from nihonco_player.core.library import CACHE


class TestLibraryIndex(unittest.TestCase):
    def setUp(self):
        self.old = dict(CACHE)
        self.old_missing = list(LIB.LAST_MISSING)
        CACHE.clear()
        self.old_lyrics = LRF.LYRICS
        self._lyr_tmp = tempfile.TemporaryDirectory()
        LRF.LYRICS = Path(self._lyr_tmp.name) / "lyrics"

    def tearDown(self):
        CACHE.clear()
        CACHE.update(self.old)
        LIB.LAST_MISSING = self.old_missing
        LRF.LYRICS = self.old_lyrics
        self._lyr_tmp.cleanup()

    def test_full_scan_prunes_stale_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "X - A.mp3"; real.touch()
            stale = root / "X - B.mp3"; stale.touch()
            with patch.object(LI, "INDEX", root / "index.json"), \
                 patch.object(LI, "_data", {}), patch.object(LI, "_dirty", False), \
                 patch.object(FP, "INDEX", root / "fp.json"), \
                 patch.object(FP, "_CACHE", {}), patch.object(FP, "_DIRTY", False), \
                 patch.object(LIB, "music_dirs", return_value=[root]), \
                 patch.object(LIB, "load_imports", return_value=[]):
                LI.put({"file": str(stale), "uid": "stale", "title": "B",
                        "artist": "X", "stem": stale.stem, "group": "g"})
                self.assertIn(str(stale), LI.paths_by_uid().get("stale", []))
                stale.unlink()
                LIB.scan_library()
                remaining = {p for paths in LI.paths_by_uid().values() for p in paths}
            self.assertIn(str(real), remaining)
            self.assertNotIn(str(stale), remaining)


if __name__ == "__main__":
    unittest.main()
