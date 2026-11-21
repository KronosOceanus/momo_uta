"""主题设置的持久化。"""
import json
import tempfile
import unittest
from pathlib import Path

from nihonco_yomi.config import PUI
from nihonco_player.core import user_config as UC
from nihonco_player.service import settings


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
