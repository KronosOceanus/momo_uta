"""默认配置只来自 config/defaults.json。"""
import unittest

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

