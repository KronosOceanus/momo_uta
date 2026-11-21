"""默认配置只来自 config/defaults.json。"""
import unittest

from nihonco_yomi.config import CFG


class TestConfig(unittest.TestCase):
    def test_default_sections_exist(self):
        for key in ("lyrics", "player", "waveform", "vocals", "library", "app", "jobs"):
            self.assertIn(key, CFG)
            self.assertIsInstance(CFG[key], dict)

    def test_vocals_timeouts(self):
        self.assertGreater(CFG["vocals"]["queue_timeout_s"], 0)
        self.assertGreater(CFG["vocals"]["run_timeout_s"], 0)


if __name__ == "__main__":
    unittest.main()
