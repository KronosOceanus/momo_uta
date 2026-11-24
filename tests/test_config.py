"""默认配置只来自 config/defaults.json。"""
import tempfile
import unittest
from pathlib import Path

from momo_yomi import config as YC
from momo_yomi.config import CFG


class TestConfig(unittest.TestCase):
    def test_default_sections_exist(self):
        for key in ("lyrics", "player", "waveform", "vocals", "library", "app", "jobs", "http"):
            self.assertIn(key, CFG)
            self.assertIsInstance(CFG[key], dict)

    def test_default_theme(self):
        self.assertIn(CFG["player"]["ui"].get("theme"), ("dark", "light"))

    def test_vocals_timeouts(self):
        self.assertGreater(CFG["vocals"]["queue_timeout_s"], 0)
        self.assertGreater(CFG["vocals"]["run_timeout_s"], 0)

    def test_runtime_limits_are_configurable(self):
        self.assertGreater(CFG["library"]["max_import_paths"], 0)
        self.assertGreater(CFG["library"]["max_scan_files"], 0)
        self.assertGreater(CFG["http"]["max_body_bytes"], 0)
        self.assertGreater(CFG["http"]["timeout_s"], 0)
        self.assertGreater(CFG["lyrics"]["max_name_bytes"], 0)

    def test_corrupt_local_config_is_backed_up(self):
        old = YC.LOCAL_CONFIG_WARNING
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text("{not json", encoding="utf-8")
            try:
                self.assertEqual(YC.read_local_config(p), {})
                self.assertFalse(p.exists())
                backups = list(Path(tmp).glob("config.json.bad-*"))
                self.assertEqual(len(backups), 1)
                self.assertIn("已备份", YC.LOCAL_CONFIG_WARNING)
            finally:
                YC.LOCAL_CONFIG_WARNING = old

    def test_non_object_local_config_is_treated_as_corrupt(self):
        old = YC.LOCAL_CONFIG_WARNING
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text("[1, 2]", encoding="utf-8")
            try:
                self.assertEqual(YC.read_local_config(p), {})
                self.assertFalse(p.exists())
                self.assertEqual(len(list(Path(tmp).glob("config.json.bad-*"))), 1)
            finally:
                YC.LOCAL_CONFIG_WARNING = old

    def test_dead_config_keys_are_gone(self):
        self.assertNotIn("scan_sleep", CFG["lyrics"])
        self.assertNotIn("coverage_warn", CFG["player"])
        self.assertNotIn("merge_same_ts", CFG["player"])
        self.assertNotIn("follow_default", CFG["player"]["ui"])
        self.assertNotIn("wave_draw_ms", CFG["player"]["ui"])
        self.assertNotIn("timeupdate_ms", CFG["player"]["ui"])
        self.assertNotIn("auto_rebuild_ms", CFG["player"]["ui"])
        self.assertNotIn("busy_retry_ms", CFG["player"]["ui"])
        self.assertNotIn("toggle_debounce_ms", CFG["player"]["ui"])


if __name__ == "__main__":
    unittest.main()

