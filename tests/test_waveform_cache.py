"""波形缓存按音频 size/mtime 失效。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import waveform


class TestWaveformCache(unittest.TestCase):
    def test_hit_checks_audio_stat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.wav"
            audio.write_bytes(b"abc")
            wave_dir = root / "wave"
            with patch.object(waveform, "WAVE_DIR", wave_dir):
                p = waveform.cache_path(str(audio), "mix")
                p.parent.mkdir(parents=True)
                st = audio.stat()
                cached = {"duration": 1, "step": waveform.STEP,
                          "audio_size": st.st_size,
                          "audio_mtime": st.st_mtime_ns,
                          "peaks": [[-1, 1]]}
                p.write_text(json.dumps(cached), encoding="utf-8")
                self.assertEqual(waveform.peaks(str(audio), "mix"), cached)

    def test_stale_cache_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.wav"
            audio.write_bytes(b"abc")
            wave_dir = root / "wave"
            with patch.object(waveform, "WAVE_DIR", wave_dir):
                p = waveform.cache_path(str(audio), "mix")
                p.parent.mkdir(parents=True)
                old = {"duration": 1, "step": waveform.STEP,
                       "audio_size": 1, "audio_mtime": 1, "peaks": []}
                p.write_text(json.dumps(old), encoding="utf-8")
                with patch.object(waveform.subprocess, "Popen",
                                  side_effect=FileNotFoundError):
                    self.assertEqual(waveform.peaks(str(audio), "mix"),
                                     {"error": "没有 ffmpeg"})


if __name__ == "__main__":
    unittest.main()


class TestWaveformSingleFlight(unittest.TestCase):
    def test_concurrent_requests_start_one_ffmpeg(self):
        import io
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.wav"; audio.write_bytes(b"abc")
            wave_dir = root / "wave"; wave_dir.mkdir()
            count = 0
            guard = threading.Lock()

            class Proc:
                stdout = io.BytesIO(b"")
                def wait(self, timeout=None):
                    return 0

            def popen(*a, **k):
                nonlocal count
                with guard:
                    count += 1
                time.sleep(0.05)
                return Proc()

            with patch.object(waveform, "WAVE_DIR", wave_dir), \
                 patch.object(waveform.subprocess, "Popen", side_effect=popen):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    list(ex.map(lambda _: waveform.peaks(str(audio), "mix"), range(2)))
            self.assertEqual(count, 1)


class TestWaveformTimeout(unittest.TestCase):
    def test_timeout_kills_ffmpeg(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.wav"; audio.write_bytes(b"abc")
            wave_dir = root / "wave"; wave_dir.mkdir()
            state = {"kill": False}

            class Proc:
                stdout = io.BytesIO(b"")
                def kill(self):
                    state["kill"] = True
                def wait(self, timeout=None):
                    return 0

            with patch.object(waveform, "WAVE_DIR", wave_dir), \
                 patch.object(waveform, "TIMEOUT", 0.01), \
                 patch.object(waveform.subprocess, "Popen", return_value=Proc()), \
                 patch.object(waveform.select, "select", return_value=([], [], [])):
                out = waveform.peaks(str(audio), "mix")
            self.assertEqual(out["error"], "波形生成超时")
            self.assertTrue(state["kill"])


class TestWaveformGlobalLimit(unittest.TestCase):
    def test_different_keys_share_global_limit(self):
        import io
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.wav"; a.write_bytes(b"a")
            b = root / "b.wav"; b.write_bytes(b"b")
            wave_dir = root / "wave"; wave_dir.mkdir()
            active = 0
            peak = 0
            guard = threading.Lock()

            class Proc:
                stdout = io.BytesIO(b"")
                def wait(self, timeout=None):
                    return 0

            def popen(*args, **kwargs):
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.05)
                with guard:
                    active -= 1
                return Proc()

            with patch.object(waveform, "WAVE_DIR", wave_dir), \
                 patch.object(waveform, "_SEM", threading.BoundedSemaphore(1)), \
                 patch.object(waveform.subprocess, "Popen", side_effect=popen):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    list(ex.map(lambda p: waveform.peaks(str(p), "mix"), (a, b)))
            self.assertEqual(peak, 1)
