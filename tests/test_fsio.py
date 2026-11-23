"""fsio：原子写、JSON 读、可重入文件锁。"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from momo_player.core import fsio


class TestFsio(unittest.TestCase):
    def test_atomic_text_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "a" / "x.json"
            fsio.atomic_write_json(p, {"v": 1}, indent=None)
            self.assertEqual(fsio.read_json(p), {"v": 1})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"v": 1})
            self.assertEqual([x.name for x in p.parent.glob(".x.json.tmp-*")], [])

    def test_lock_is_reentrant(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "x.lock"
            with fsio.locked(lock):
                with fsio.locked(lock):
                    self.assertTrue(lock.exists())

    def test_lock_serializes_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "x.lock"
            active = 0
            peak = 0
            guard = threading.Lock()

            def work():
                nonlocal active, peak
                with fsio.locked(lock):
                    with guard:
                        active += 1
                        peak = max(peak, active)
                    import time
                    time.sleep(0.02)
                    with guard:
                        active -= 1

            threads = [threading.Thread(target=work) for _ in range(3)]
            for t in threads: t.start()
            for t in threads: t.join()
            self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
