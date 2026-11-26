"""全局热键：非 macOS 不注册；未安装时注销安全。"""
import unittest
from unittest.mock import patch

from momo_uta_app import hotkeys as H


class FakeCarbon:
    """MagicMock 版本由测试构造；这里只保留可读的替身说明。"""


class TestHotkeys(unittest.TestCase):
    def tearDown(self):
        H.uninstall()

    def test_non_darwin_reports_all_failed(self):
        with patch.object(H.sys, "platform", "linux"):
            r = H.install(lambda name: None)
        self.assertFalse(r["installed"])
        self.assertEqual(set(r["failed"]), set(H.BINDINGS))
        self.assertEqual(r["registered"], [])

    def test_uninstall_is_idempotent(self):
        H.uninstall()
        H.uninstall()

    def test_partial_registration_keeps_successes_and_uninstalls(self):
        from unittest.mock import MagicMock
        fake = MagicMock()
        fake.GetApplicationEventTarget.return_value = 1
        fake.InstallEventHandler.return_value = 0
        fake.RegisterEventHotKey.side_effect = lambda code, mods, hkid, target, options, ref: (
            0 if hkid.id in (1, 3) else -1)
        with patch.object(H.sys, "platform", "darwin"), \
             patch.object(H.ctypes.util, "find_library", return_value="/fake/Carbon"), \
             patch.object(H.ctypes, "CDLL", return_value=fake):
            r = H.install(lambda name: None)
        self.assertTrue(r["installed"])
        self.assertEqual(r["registered"], ["prev", "toggle"])
        self.assertEqual(r["failed"], ["next"])
        H.uninstall()
        self.assertEqual(fake.UnregisterEventHotKey.call_count, 2)
