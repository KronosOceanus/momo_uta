"""人声分离：VAD 统计与缓存路径（不跑 demucs 本体）。"""
import array
import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import vocals


def _write_wav(path: Path, segments):
    """segments: [(秒数, 振幅)]，16k 单声道。"""
    rate = vocals.SAMPLE_RATE
    frames = array.array("h")
    for sec, amp in segments:
        n = int(sec * rate)
        for i in range(n):
            frames.append(int(amp * 32767 * math.sin(2 * math.pi * 220 * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())


class TestVocalStats(unittest.TestCase):
    def test_song_with_vocals_has_high_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "v.wav"
            _write_wav(p, [(1.0, 0.0), (2.0, 0.5), (1.0, 0.0), (2.0, 0.5)])
            s = vocals.analyze(p)
            self.assertGreater(s["ratio"], 0.3)
            self.assertAlmostEqual(s["duration"], 6.0, delta=0.1)

    def test_silence_has_zero_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "v.wav"
            _write_wav(p, [(3.0, 0.0)])
            s = vocals.analyze(p)
            self.assertEqual(s["ratio"], 0.0)

    def test_status_none_then_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(vocals, "VOCALS", Path(tmp)):
                uid = "abc123"
                self.assertEqual(vocals.status(uid)["state"], "none")
                d, wav, meta = vocals.paths(uid)
                d.mkdir(parents=True)
                wav.write_bytes(b"")
                meta.write_text('{"has_vocals": true, "ratio": 0.4, "duration": 10}')
                st = vocals.status(uid)
                self.assertEqual(st["state"], "done")
                self.assertTrue(st["has_vocals"])


if __name__ == "__main__":
    unittest.main()
