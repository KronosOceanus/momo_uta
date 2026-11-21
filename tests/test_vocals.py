"""人声分离：VAD 统计与缓存路径（不跑 demucs 本体）。"""
import array
import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import vocals
from nihonco_player.core import vocals as vocals_mod


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


class TestVocalTimeout(unittest.TestCase):
    def test_demucs_timeout_kills_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(vocals_mod, "VOCALS", root / "vocals"), \
                 patch.object(vocals_mod, "TMP_ROOT", root / "tmp" / "vocals"), \
                 patch.object(vocals_mod, "installed", return_value=True), \
                 patch.object(vocals_mod, "_run_process",
                              side_effect=RuntimeError("人声分离执行超时")):
                with self.assertRaises(RuntimeError) as cm:
                    vocals_mod._separate("uid-timeout", str(root / "a.mp3"))
            self.assertIn("超时", str(cm.exception))
            self.assertEqual(list((root / "tmp" / "vocals").glob("*")), [])

    def test_timeout_kills_child_process_group(self):
        import os
        import subprocess
        import sys
        import time
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "child.pid"
            child = "import time; time.sleep(30)"
            parent = ("import subprocess,sys,time;"
                      "p=subprocess.Popen([sys.executable,'-c',%r]);"
                      "open(%r,'w').write(str(p.pid));time.sleep(30)"
                      % (child, str(pidfile)))
            with self.assertRaises(RuntimeError) as cm:
                vocals_mod._run_process([sys.executable, "-c", parent],
                                        timeout=0.6)
            self.assertIn("超时", str(cm.exception))
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    pid = int(pidfile.read_text())
                except Exception:
                    time.sleep(0.05); continue
                ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                    capture_output=True, text=True)
                if not ps.stdout.strip() or ps.stdout.strip().startswith("Z"):
                    break
                time.sleep(0.05)
            else:
                self.fail("辅助子进程仍然存活")


class TestVocalCleanup(unittest.TestCase):
    def test_cleanup_removes_orphans_and_tmp_but_keeps_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vocals = root / "vocals"
            job = root / "tmp" / "vocals" / "job"
            job.mkdir(parents=True)
            for uid in ("keep", "orphan"):
                d = vocals / uid
                d.mkdir(parents=True)
                (d / "vocals.wav").write_bytes(b"x" * 10)
                (d / "meta.json").write_text('{"created":1,"last_used":1}', encoding="utf-8")
            with patch.object(vocals_mod, "VOCALS", vocals), \
                 patch.object(vocals_mod, "TMP_ROOT", root / "tmp" / "vocals"), \
                 patch.object(vocals_mod, "_states", {}):
                res = vocals_mod.cleanup(protected={"keep"})
            self.assertTrue((vocals / "keep" / "vocals.wav").is_file())
            self.assertFalse((vocals / "orphan").exists())
            self.assertFalse(job.exists())
            self.assertIn("orphan", res["removed"])

    def test_cleanup_cap_evicts_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vocals = root / "vocals"
            for uid, used in (("old", 1), ("new", 2)):
                d = vocals / uid
                d.mkdir(parents=True)
                (d / "vocals.wav").write_bytes(b"x" * 100)
                (d / "meta.json").write_text(
                    '{"created":%d,"last_used":%d}' % (used, used), encoding="utf-8")
            with patch.object(vocals_mod, "VOCALS", vocals), \
                 patch.object(vocals_mod, "TMP_ROOT", root / "tmp" / "vocals"), \
                 patch.object(vocals_mod, "_states", {}):
                res = vocals_mod.cleanup(protected={"old", "new"}, max_bytes=150)
            self.assertFalse((vocals / "old").exists())
            self.assertTrue((vocals / "new" / "vocals.wav").is_file())
            self.assertIn("old", res["removed"])


if __name__ == "__main__":
    unittest.main()
