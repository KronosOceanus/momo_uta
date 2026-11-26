"""全局热键：非 macOS 不注册；未安装时注销安全。"""
import unittest
from unittest.mock import patch

from momo_uta_app import hotkeys as H


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
