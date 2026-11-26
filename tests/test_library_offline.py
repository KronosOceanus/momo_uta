import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import library as LIB
from momo_player.core import fingerprint as FP
from momo_player.core import library_index as LI
from momo_player.core import playlists as PL


class TestOfflineLibrary(unittest.TestCase):
    def test_missing_root_skips_startup_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "offline" / "a.mp3"
            old = list(LIB.LAST_MISSING)
            try:
                LIB.LAST_MISSING = []
                with patch.object(LIB, "music_dirs", return_value=[missing.parent]), \
                     patch.object(PL, "all_uids", return_value=["u1"]), \
                     patch.object(FP, "paths_for_uids", return_value={"u1": [str(missing)]}), \
                     patch.object(LI, "paths_by_uid", return_value={}), \
                     patch.object(LIB, "load_imports", return_value=[]), \
                     patch.object(LI, "meta", return_value={}), \
                     patch.object(LI, "set_meta") as set_meta, \
                     patch.object(LI, "prune_paths") as li_prune, \
                     patch.object(FP, "prune_paths") as fp_prune, \
                     patch.object(LI, "flush"):
                    lib = LIB.load_for_playlists()
                self.assertEqual(lib, [])
                li_prune.assert_not_called()
                fp_prune.assert_not_called()
                self.assertTrue(set_meta.call_args.args[0].get("last_offline"))
            finally:
                LIB.LAST_MISSING = old

    def test_scan_with_missing_root_does_not_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "offline"
            with patch.object(LIB, "music_dirs", return_value=[missing]), \
                 patch.object(LIB, "load_imports", return_value=[]), \
                 patch.object(LI, "prune") as li_prune, \
                 patch.object(FP, "prune") as fp_prune, \
                 patch.object(LI, "flush"), patch.object(FP, "flush"):
                self.assertEqual(LIB.scan_library(), [])
            li_prune.assert_not_called()
            fp_prune.assert_not_called()

    def test_offline_meta_allows_retry_after_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = list(LIB.LAST_MISSING)
            try:
                LIB.LAST_MISSING = ["u1"]
                with patch.object(LIB, "music_dirs", return_value=[root / "offline"]):
                    self.assertFalse(LIB.should_auto_rebuild())
                with patch.object(LIB, "music_dirs", return_value=[root]), \
                     patch.object(LI, "meta", return_value={"last_offline": True}):
                    self.assertTrue(LIB.should_auto_rebuild())
            finally:
                LIB.LAST_MISSING = old


if __name__ == "__main__":
    unittest.main()
