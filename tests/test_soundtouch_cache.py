import os
import tempfile
import threading
import time
import unittest
import wave
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

    def test_valid_wav_checks_format_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ok.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"\x00" * 4)
            self.assertTrue(ST._valid_wav(p))
            p.write_bytes(b"RIFF" + b"\x00" * 100)
            self.assertFalse(ST._valid_wav(p))

    def test_corrupt_cache_is_removed_before_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "u-0.80.wav"
            bad.write_bytes(b"RIFF" + b"\x00" * 100)
            item = {"uid": "u", "file": str(root / "source.mp3")}
            Path(item["file"]).write_bytes(b"x")
            with patch.object(ST, "CACHE_DIR", root), \
                 patch.object(ST.LIB, "resolve", return_value=item), \
                 patch.object(ST, "_tool", return_value="/bin/true"), \
                 patch.object(ST, "_run", side_effect=RuntimeError("stop")):
                with self.assertRaises(RuntimeError):
                    ST.process("u", 0.80)
            self.assertFalse(bad.exists())

    def test_cache_read_is_not_blocked_by_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp3"
            source.write_bytes(b"x")
            item = {"uid": "a", "file": str(source)}
            cache = root / "soundtouch"
            cache.mkdir()
            with wave.open(str(cache / "b-0.80.wav"), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"\x00" * 4)
            started = threading.Event()
            release = threading.Event()
            errors = []

            def fake_run(_cmd, _uid, _gen):
                started.set()
                release.wait(2)

            def work():
                try:
                    ST.process("a", 0.80)
                except Exception as e:
                    errors.append(type(e).__name__)

            with patch.object(ST, "CACHE", root), \
                 patch.object(ST, "CACHE_DIR", cache), \
                 patch.object(ST.LIB, "resolve", return_value=item), \
                 patch.object(ST, "_tool", return_value="/bin/true"), \
                 patch.object(ST, "_run", side_effect=fake_run):
                t = threading.Thread(target=work)
                t.start()
                self.assertTrue(started.wait(1))
                t0 = time.monotonic()
                got = ST.cached_path("b", 0.80)
                elapsed = time.monotonic() - t0
                release.set()
                t.join(3)
            self.assertIsNotNone(got)
            self.assertLess(elapsed, 0.5)
            self.assertFalse(t.is_alive())

    def test_startup_cleanup_removes_old_temp_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "momo-st-old"
            new = root / "momo-st-new"
            old.mkdir(); new.mkdir()
            os.utime(old, (1, 1))
            with patch.object(ST, "CACHE", root), \
                 patch.object(ST, "CACHE_DIR", root / "soundtouch"), \
                 patch.object(ST, "TMP_MAX_AGE", 10):
                ST.cleanup_startup()
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())

    def test_cached_path_only_returns_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(ST, "CACHE_DIR", root):
                self.assertIsNone(ST.cached_path("u", 0.80))
                p = root / "u-0.80.wav"
                p.write_bytes(b"RIFF" + b"\x00" * 100)
                self.assertIsNone(ST.cached_path("u", 0.80))
                self.assertFalse(p.exists())

    def test_cancel_without_uid_stops_current_process(self):
        uid = "shutdown-test"
        gen = ST._cancel_gen(uid)
        result = []

        def work():
            try:
                ST._run(["sleep", "10"], uid, gen)
            except Exception as e:
                result.append(type(e).__name__)

        t = threading.Thread(target=work)
        t.start()
        deadline = time.time() + 2
        while ST._CURRENT is None and time.time() < deadline:
            time.sleep(0.01)
        ST.cancel()
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertIsNone(ST._CURRENT)
        self.assertTrue(result)

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
