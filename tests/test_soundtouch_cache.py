import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.service import soundtouch as ST


class TestSoundTouchCache(unittest.TestCase):
    def test_lru_removes_oldest_wav_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for i in range(3):
                p = root / f"{i}.wav"
                p.write_bytes(b"x" * 4)
                os.utime(p, (1000 + i, 1000 + i))
                files.append(p)
            with patch.object(ST, "CACHE_DIR", root), \
                 patch.object(ST, "MAX_CACHE_BYTES", 8):
                ST._cleanup(keep=files[-1])
            self.assertFalse(files[0].exists())
            self.assertTrue(files[1].exists())
            self.assertTrue(files[2].exists())

    def test_old_temp_dirs_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "momo-st-old"
            old.mkdir()
            (old / "x").write_text("x", encoding="utf-8")
            os.utime(old, (1, 1))
            with patch.object(ST, "CACHE", root), \
                 patch.object(ST, "CACHE_DIR", root / "soundtouch"), \
                 patch.object(ST, "TMP_MAX_AGE", 10):
                ST._cleanup()
            self.assertFalse(old.exists())

    def test_touch_updates_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            p.write_bytes(b"x")
            os.utime(p, (1, 1))
            ST._touch(p)
            self.assertGreater(p.stat().st_mtime, 1000)


if __name__ == "__main__":
    unittest.main()
