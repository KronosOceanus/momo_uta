"""主题设置的持久化。"""
import json
import tempfile
import unittest
from pathlib import Path

from momo_yomi import config as YC
from momo_yomi.config import PUI
from momo_player.core import user_config as UC
from momo_player.service import settings


class TestThemeSetting(unittest.TestCase):
    def test_set_theme_persists_and_updates_memory(self):
        old_file, old_lock, old_theme = UC.FILE, UC.LOCK, PUI.get("theme")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            UC.FILE, UC.LOCK = p, p.with_suffix(".lock")
            try:
                r = settings.set_theme({"theme": "light"})
                self.assertTrue(r["ok"])
                self.assertEqual(PUI["theme"], "light")
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"player": {"ui": {"theme": "light"}}})
                self.assertFalse(settings.set_theme({"theme": "blue"})["ok"])
            finally:
                UC.FILE, UC.LOCK = old_file, old_lock
                PUI["theme"] = old_theme


if __name__ == "__main__":
    unittest.main()


class TestPlayModeSetting(unittest.TestCase):
    def test_set_play_mode_persists_and_updates_memory(self):
        old_file, old_lock, old_mode = UC.FILE, UC.LOCK, PUI.get("play_mode")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            UC.FILE, UC.LOCK = p, p.with_suffix(".lock")
            try:
                r = settings.set_play_mode({"mode": "shuffle"})
                self.assertTrue(r["ok"])
                self.assertEqual(PUI["play_mode"], "shuffle")
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"player": {"ui": {"play_mode": "shuffle"}}})
                self.assertFalse(settings.set_play_mode({"mode": "nope"})["ok"])
            finally:
                UC.FILE, UC.LOCK = old_file, old_lock
                PUI["play_mode"] = old_mode


class TestCorruptConfigWrite(unittest.TestCase):
    def test_corrupt_config_is_backed_up_before_write(self):
        old_file, old_lock, old_theme = UC.FILE, UC.LOCK, PUI.get("theme")
        old_warn = YC.LOCAL_CONFIG_WARNING
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text("{bad", encoding="utf-8")
            UC.FILE, UC.LOCK = p, p.with_suffix(".lock")
            try:
                r = settings.set_theme({"theme": "light"})
                self.assertTrue(r["ok"])
                self.assertEqual(len(list(Path(tmp).glob("config.json.bad-*"))), 1)
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"player": {"ui": {"theme": "light"}}})
            finally:
                UC.FILE, UC.LOCK = old_file, old_lock
                PUI["theme"] = old_theme
                YC.LOCAL_CONFIG_WARNING = old_warn
