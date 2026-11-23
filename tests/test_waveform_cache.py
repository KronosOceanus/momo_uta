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
