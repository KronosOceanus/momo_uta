import os
import tempfile
import threading
import time
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

    def test_cancel_stops_active_generation(self):
        uid = "cancel-test"
        gen = ST._cancel_gen(uid)
        err = []

        def work():
            try:
                ST._run(["sleep", "10"], uid, gen)
            except ST.Cancelled:
                err.append("cancelled")

        t = threading.Thread(target=work)
        t.start()
        deadline = time.time() + 2
        while ST._CURRENT is None and time.time() < deadline:
            time.sleep(0.01)
        ST.cancel(uid)
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertEqual(err, ["cancelled"])

    def test_touch_updates_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            p.write_bytes(b"x")
            os.utime(p, (1, 1))
            ST._touch(p)
            self.assertGreater(p.stat().st_mtime, 1000)


    def test_run_times_out_and_stops(self):
        uid = "timeout-test"
        gen = ST._cancel_gen(uid)
        with patch.object(ST, "RUN_TIMEOUT", 0.05):
            with self.assertRaises(TimeoutError):
                ST._run(["sleep", "10"], uid, gen)
        self.assertIsNone(ST._CURRENT)

    def test_tool_requires_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "soundstretch"
            p.write_text("#!/bin/sh\n", encoding="utf-8")
            p.chmod(0o644)
            with patch.dict(os.environ, {"MOMO_SOUNDSTRETCH": str(p)}, clear=False), \
                 patch.object(ST.shutil, "which", return_value=None), \
                 patch.object(ST.sys, "frozen", False, create=True):
                self.assertIsNone(ST._tool("soundstretch", "MOMO_SOUNDSTRETCH"))

    def test_cancel_idle_uid_does_not_accumulate(self):
        uid = "idle-cancel-test"
        ST.cancel(uid)
        self.assertNotIn(uid, ST._CANCEL_GEN)


if __name__ == "__main__":
    unittest.main()
