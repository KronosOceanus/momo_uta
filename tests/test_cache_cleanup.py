import json
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import annotation_cache as ANNO
from momo_player.core import cache_cleanup as C


class TestCacheCleanup(unittest.TestCase):
    def test_wave_old_params_and_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wave"
            root.mkdir()
            fresh = root / f"a.mix.{C.WAVE.RATE}.{C.WAVE.STEP}.json"
            fresh.write_text("{}", encoding="utf-8")
            oldparam = root / "a.mix.44100.0.01.json"
            oldparam.write_text("{}", encoding="utf-8")
            old = root / f"b.mix.{C.WAVE.RATE}.{C.WAVE.STEP}.json"
            old.write_text("{}", encoding="utf-8")
            os.utime(old, (1, 1))
            with patch.object(C, "CACHE", Path(tmp)):
                C._cleanup_wave(time.time())
            self.assertTrue(fresh.exists())
            self.assertFalse(oldparam.exists())
            self.assertFalse(old.exists())

    def test_annotation_version_and_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ann"
            root.mkdir()
            good = root / "good.json"
            good.write_text(json.dumps({"v": ANNO.VERSION}), encoding="utf-8")
            oldver = root / "old.json"
            oldver.write_text(json.dumps({"v": "old"}), encoding="utf-8")
            bad = root / "bad.json"
            bad.write_text("not json", encoding="utf-8")
            with patch.object(C.ANNO, "CACHE_DIR", root):
                C._cleanup_annotations(time.time())
            self.assertTrue(good.exists())
            self.assertFalse(oldver.exists())
            self.assertFalse(bad.exists())

    def test_lyrics_negative_ttl_and_positive_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lyrics"
            root.mkdir()
            fresh_neg = root / "fresh.json"
            fresh_neg.write_text(json.dumps({"miss": True, "checked_at": 10**12}),
                                  encoding="utf-8")
            old_neg = root / "oldneg.json"
            old_neg.write_text(json.dumps({"miss": True, "checked_at": 1}),
                                encoding="utf-8")
            fresh_pos = root / "freshpos.json"
            fresh_pos.write_text(json.dumps({"lrc": "x"}), encoding="utf-8")
            old_pos = root / "oldpos.json"
            old_pos.write_text(json.dumps({"lrc": "x"}), encoding="utf-8")
            os.utime(old_pos, (1, 1))
            with patch.object(C.LYC, "CACHE", root):
                C._cleanup_lyrics(time.time())
            self.assertTrue(fresh_neg.exists())
            self.assertFalse(old_neg.exists())
            self.assertTrue(fresh_pos.exists())
            self.assertFalse(old_pos.exists())


if __name__ == "__main__":
    unittest.main()
