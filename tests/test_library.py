"""歌曲库：扫描、缓存命中、标签隐藏。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from nihonco_player.core import library as LIB  # noqa: E402


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "歌手A - 曲A.mp3").write_bytes(b"x")
        (self.dir / "歌手B - 曲B.mp3").write_bytes(b"x")
        (self.dir / "english only.mp3").write_bytes(b"x")      # 非日文名 → 跳过
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir()
        LIB.LY.set_cache_dir(self.cache)
        self._tags = LIB.TAGS
        LIB.TAGS = self.dir / "tags.json"

    def tearDown(self):
        LIB.LY.set_cache_dir(Path.home() / "Documents" / "nihonco_uta" / "data" / "cache" / "lyrics")
        LIB.TAGS = self._tags
        self.tmp.cleanup()

    def _write_hit(self, title, artist, lrc="[00:01.00]あ\n[00:02.00]い\n[00:03.00]う"):
        p = LIB.LY.cache_path(title, artist)
        p.write_text(json.dumps({"lrc": lrc, "name": title, "artist": artist,
                                 "lang": "ja"}), encoding="utf-8")

    def test_scan_includes_without_cache_as_no_lyric(self):
        """没有歌词也列出来，只是标记 has_lyric=False（点开时懒匹配）。"""
        rows = LIB.scan_library(self.dir)
        self.assertTrue(rows)
        self.assertTrue(all(r["has_lyric"] is False for r in rows))

    def test_scan_picks_up_cached(self):
        self._write_hit("曲A", "歌手A")
        rows = LIB.scan_library(self.dir)
        with_lyric = [r for r in rows if r["has_lyric"]]
        self.assertEqual(len(with_lyric), 1)
        self.assertEqual(with_lyric[0]["title"], "曲A")
        self.assertEqual(len(with_lyric[0]["key"]), 12)
        self.assertEqual(len(with_lyric[0]["uid"]), 12)

    def test_metadata_only_lyrics_counts_as_no_lyric(self):
        """只有作词/作曲的行 → 当没歌词。"""
        self._write_hit("曲A", "歌手A", lrc="[00:00.00-1] 作词 : X")
        rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertFalse(rows[0]["has_lyric"])

    def test_tags_roundtrip(self):
        LIB.save_tags({"abc": ["inst"]})
        self.assertEqual(LIB.load_tags(), {"abc": ["inst"]})

    def test_hidden_tags_constant(self):
        self.assertEqual(LIB.HIDDEN_TAGS, {"inst", "nonja"})


if __name__ == "__main__":
    unittest.main()
