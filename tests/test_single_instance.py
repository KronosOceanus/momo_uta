"""单实例锁：同一 data 目录只允许一个进程启动。"""
import tempfile
import unittest
from pathlib import Path

from momo_uta_app.__main__ import _acquire_instance_lock


class TestSingleInstance(unittest.TestCase):
    def test_second_lock_is_rejected_until_first_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "app.lock"
            first = _acquire_instance_lock(p)
            self.assertIsNotNone(first)
            self.assertIsNone(_acquire_instance_lock(p))
            first.close()
            second = _acquire_instance_lock(p)
            self.assertIsNotNone(second)
            second.close()
