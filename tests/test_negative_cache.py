"""歌词负缓存 TTL。"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from momo_player.core import lyrics_cache as LC
from momo_player.core import lyrics_fetch as LF


class TestNegativeCache(unittest.TestCase):
    def test_fresh_miss_is_reused_and_expired_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, old_ttl = LC.CACHE, LF.CFG.get("negative_ttl_days")
            LC.set_cache_dir(Path(tmp))
            LF.CFG["negative_ttl_days"] = 7
            try:
                p = LC.cache_path("曲", "歌手")
                p.write_text(json.dumps({"miss": True, "checked_at": time.time()}),
                             encoding="utf-8")
                with patch.object(LF, "auto_match_status",
                                  return_value=(None, "no_match")) as am:
                    self.assertTrue(LF.get_lrc("曲", "歌手")["miss"])
                    am.assert_not_called()

                p.write_text(json.dumps({"miss": True, "checked_at": time.time() - 8 * 86400}),
                             encoding="utf-8")
                with patch.object(LF, "auto_match_status",
                                  return_value=(None, "no_match")) as am:
                    self.assertIsNone(LF.get_lrc("曲", "歌手"))
                    am.assert_called_once()
                    self.assertIn("checked_at", json.loads(p.read_text(encoding="utf-8")))
            finally:
                LF.CFG["negative_ttl_days"] = old_ttl
                LC.set_cache_dir(old_dir)


if __name__ == "__main__":
    unittest.main()


class TestMatchStatus(unittest.TestCase):
    def test_network_error_is_not_negative_cached(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = LC.CACHE
            LC.set_cache_dir(Path(tmp))
            try:
                with patch.object(LF, "_get", return_value=""):
                    hit, status = LF.get_lrc_status("曲", "歌手")
                self.assertIsNone(hit)
                self.assertEqual(status, LF.MATCH_NETWORK)
                self.assertFalse(LC.cache_path("曲", "歌手").exists())
            finally:
                LC.set_cache_dir(old_dir)

    def test_no_match_is_negative_cached_with_reason(self):
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = LC.CACHE
            LC.set_cache_dir(Path(tmp))
            try:
                with patch.object(LF, "_get",
                                  return_value=json.dumps({"result": {"songs": []}})):
                    hit, status = LF.get_lrc_status("曲", "歌手")
                self.assertIsNone(hit)
                self.assertEqual(status, LF.MATCH_NO_MATCH)
                raw = json.loads(LC.cache_path("曲", "歌手").read_text(encoding="utf-8"))
                self.assertTrue(raw["miss"])
                self.assertEqual(raw["reason"], "no_match")
            finally:
                LC.set_cache_dir(old_dir)
