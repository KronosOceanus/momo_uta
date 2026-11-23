"""音频指纹：与路径无关、内容变才变、索引可复用。"""
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from momo_player.core import fingerprint as FP
from momo_player.core import lrc_doc as DOC
from momo_player.core import lrc_files as LRF
from momo_player.core import lyrics as LY


def make_wav(path: Path, freq: float = 440.0, seconds: float = 1.0) -> None:
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


class TestFingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        with patch.object(FP, "INDEX", self.root / "fp.json"):
            FP._CACHE = None
            FP._DIRTY = False

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_bytes_different_path(self):
        a = self.root / "a.wav"
        make_wav(a)
        b = self.root / "sub" / "b.wav"
        b.parent.mkdir()
        shutil.copy2(a, b)
        with patch.object(FP, "INDEX", self.root / "fp.json"):
            self.assertEqual(FP.fingerprint(a), FP.fingerprint(b))

    def test_content_change_changes_fingerprint(self):
        a = self.root / "a.wav"
        make_wav(a)
        with patch.object(FP, "INDEX", self.root / "fp.json"):
            fp1 = FP.fingerprint(a)
        data = bytearray(a.read_bytes())
        data[len(data) // 2] ^= 0xFF
        a.write_bytes(bytes(data))
        with patch.object(FP, "INDEX", self.root / "fp2.json"):
            fp2 = FP.fingerprint(a)
        self.assertNotEqual(fp1, fp2)

    def test_index_reuse(self):
        a = self.root / "a.wav"
        make_wav(a)
        with patch.object(FP, "INDEX", self.root / "fp.json"):
            fp1 = FP.fingerprint(a)
            FP.flush()
            FP._CACHE = None
            with patch.object(FP, "_samples", side_effect=AssertionError("不该重算")):
                self.assertEqual(FP.fingerprint(a), fp1)

    def test_read_error_falls_back_to_path(self):
        missing = self.root / "nope.mp3"
        with patch.object(FP, "INDEX", self.root / "fp.json"):
            self.assertEqual(FP.fingerprint(missing), LRF.uid_of(missing))


class TestStoreUsesFingerprint(unittest.TestCase):
    def test_lyrics_file_found_after_audio_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.wav"
            make_wav(audio)
            ann = {0: [["君", "きみ", "A"]]}
            with patch.object(FP, "INDEX", root / "fp.json"), \
                 patch.object(LRF, "LYRICS", root / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=1.0):
                LRF.save(audio, [{"t": 1.0, "text": "君"}], ann)
                fp = LRF.uid_of(audio)
                store = LRF.store_path(audio)
                self.assertIn(fp, store.name)
                moved = root / "新目录" / "改名后的歌.wav"
                moved.parent.mkdir()
                shutil.move(str(audio), moved)
                self.assertEqual(LRF.store_path(moved), store)
                self.assertEqual(LRF.load(moved)["annotations"], ann)


if __name__ == "__main__":
    unittest.main()
