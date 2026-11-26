"""歌曲库：扫描、缓存命中。"""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from momo_player.core import library as LIB  # noqa: E402
from momo_player.core import lrc_files as LRF  # noqa: E402


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
        self.old_lyrics = LRF.LYRICS
        LRF.LYRICS = self.dir / "lyrics"

    def tearDown(self):
        LIB.LY.set_cache_dir(Path.home() / "Documents" / "momo_uta" / "data" / "cache" / "lyrics")
        LRF.LYRICS = self.old_lyrics
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

    def test_nhlrc_without_cache_counts_as_lyric(self):
        audio = self.dir / "歌手A - 曲A.mp3"
        with patch.object(LRF, "LYRICS", self.dir / "lyrics"), \
             patch.object(LRF.LY, "audio_duration", return_value=60):
            LRF.save(audio, [{"t": 1.0, "text": "あの日"},
                             {"t": 2.0, "text": "今も"},
                             {"t": 3.0, "text": "空を"}], {})
            rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertTrue(rows[0]["has_lyric"])

    def test_nhlrc_scan_never_uses_network(self):
        audio = self.dir / "歌手A - 曲A.mp3"
        seen = []
        orig = LIB.LY.get_lrc

        def fake(title, artist, use_cache=True, duration=0.0, force=False, network=True):
            seen.append(network)
            return orig(title, artist, use_cache=use_cache, duration=duration,
                        force=force, network=False)

        with patch.object(LRF, "LYRICS", self.dir / "lyrics"), \
             patch.object(LRF.LY, "audio_duration", return_value=60), \
             patch.object(LIB.LY, "get_lrc", side_effect=fake):
            LRF.save(audio, [{"t": 1.0, "text": "あの日"},
                             {"t": 2.0, "text": "今も"},
                             {"t": 3.0, "text": "空を"}], {})
            rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertTrue(rows[0]["has_lyric"])
        self.assertTrue(seen)
        self.assertTrue(all(v is False for v in seen))

    def test_refresh_keeps_v2_has_lyric(self):
        audio = self.dir / "歌手A - 曲A.mp3"
        with patch.object(LRF, "LYRICS", self.dir / "lyrics"), \
             patch.object(LRF.LY, "audio_duration", return_value=60):
            LRF.save(audio, [{"t": 1.0, "text": "あの日"},
                             {"t": 2.0, "text": "今も"},
                             {"t": 3.0, "text": "空を"}], {})
            rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertTrue(rows[0]["has_lyric"])
        old = dict(LIB.CACHE)
        LIB.CACHE.clear()
        try:
            LIB.CACHE["0"] = dict(rows[0])
            LIB.refresh(rows[0]["uid"])
            self.assertTrue(LIB.CACHE["0"]["has_lyric"])
        finally:
            LIB.CACHE.clear()
            LIB.CACHE.update(old)

    def test_cache_only_entry_after_index_has_lyric(self):
        """索引命中 rec 时也必须按 title, artist 查缓存，不能只看 nhlrc。"""
        self._write_hit("曲A", "歌手A")
        LIB.scan_library(self.dir)
        rows = LIB.scan_library(self.dir)
        target = [r for r in rows if r["stem"].endswith("曲A")]
        self.assertTrue(target)
        self.assertTrue(target[0]["has_lyric"])

    def test_metadata_only_v2_blocks_cache(self):
        audio = self.dir / "歌手A - 曲A.mp3"
        self._write_hit("曲A", "歌手A")
        res = LRF.save_rows(audio, [{"kind": "metadata", "text": "[ar:X]"}])
        self.assertTrue(res.get("ok"))
        self.assertFalse(LRF.store_index({LIB.FP.fingerprint(audio)}).get(LIB.FP.fingerprint(audio), True))
        rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertFalse(rows[0]["has_lyric"])

    def test_empty_nhlrc_is_not_lyric(self):
        audio = self.dir / "歌手A - 曲A.mp3"
        with patch.object(LRF, "LYRICS", self.dir / "lyrics"):
            LRF.store_path(audio).parent.mkdir(parents=True, exist_ok=True)
            LRF.store_path(audio).write_text("", encoding="utf-8")
            rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertFalse(rows[0]["has_lyric"])

    def test_untimed_network_cache_is_not_lyric(self):
        self._write_hit("曲A", "歌手A", "[00:01.00]あ\n[00:02.00]い\n[00:03.00]う")
        # 网络缓存必须带时间轴
        p = LIB.LY.cache_path("曲A", "歌手A")
        import json
        d = json.loads(p.read_text(encoding="utf-8"))
        d["lrc"] = "あ\nい\nう"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertFalse(rows[0]["has_lyric"])

    def test_scan_picks_up_cached(self):
        self._write_hit("曲A", "歌手A")
        rows = LIB.scan_library(self.dir)
        with_lyric = [r for r in rows if r["has_lyric"]]
        self.assertEqual(len(with_lyric), 1)
        self.assertEqual(with_lyric[0]["title"], "曲A")
        self.assertEqual(len(with_lyric[0]["key"]), 12)
        self.assertEqual(len(with_lyric[0]["uid"]), 12)

    def test_scan_no_folder_uses_music_dirs(self):
        with patch.object(LIB, "music_dirs", return_value=[self.dir]), \
             patch.object(LIB, "load_imports", return_value=[]):
            rows = LIB.scan_library()
        self.assertTrue(rows)
        self.assertTrue(all(str(x["file"]).startswith(str(self.dir)) for x in rows))

    def test_metadata_only_lyrics_counts_as_no_lyric(self):
        """只有作词/作曲的行 → 当没歌词。"""
        self._write_hit("曲A", "歌手A", lrc="[00:00.00-1] 作词 : X")
        rows = [r for r in LIB.scan_library(self.dir) if r["stem"].endswith("曲A")]
        self.assertTrue(rows)
        self.assertFalse(rows[0]["has_lyric"])


if __name__ == "__main__":
    unittest.main()


class TestImportsData(unittest.TestCase):
    def test_malformed_imports_are_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "imports.json"
            old = LIB.IMPORTS
            LIB.IMPORTS = path
            try:
                path.write_text('{"audio": "x"}', encoding="utf-8")
                self.assertEqual(LIB.load_imports(), [])
                path.write_text(json.dumps([
                    None, "x", 3,
                    {"audio": 1}, {"audio": ""},
                    {"audio": "/a.mp3", "title": 1, "artist": None},
                    {"audio": "/a.mp3"},
                    {"audio": "/b.mp3", "title": "B", "artist": "X"},
                ]), encoding="utf-8")
                rows = LIB.load_imports()
                self.assertEqual(rows, [
                    {"audio": "/a.mp3", "title": "", "artist": ""},
                    {"audio": "/b.mp3", "title": "B", "artist": "X"},
                ])
            finally:
                LIB.IMPORTS = old

    def test_save_import_recovers_from_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "imports.json"
            old = LIB.IMPORTS
            LIB.IMPORTS = path
            try:
                path.write_text('{"broken": true}', encoding="utf-8")
                LIB.save_import("/a.mp3", "A", "X")
                self.assertEqual(LIB.load_imports(),
                                 [{"audio": "/a.mp3", "title": "A", "artist": "X"}])
            finally:
                LIB.IMPORTS = old


class TestEmptyNhlrcFallback(unittest.TestCase):
    def test_empty_nhlrc_does_not_block_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"; audio.write_bytes(b"audio")
            cache = root / "cache"; cache.mkdir(); LIB.LY.set_cache_dir(cache)
            old_lyrics = LRF.LYRICS
            LRF.LYRICS = root / "lyrics"
            try:
                title, artist = "曲", "歌手"
                p = LIB.LY.cache_path(title, artist)
                p.write_text(json.dumps({"lrc": "[00:01.00]缓存歌词\n[00:02.00]第二句\n[00:03.00]第三句",
                                         "name": title, "artist": artist}), encoding="utf-8")
                uid = LIB.FP.fingerprint(audio)
                sp = LRF.store_path(audio, uid, title, artist)
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text("", encoding="utf-8")
                doc = LRF.load(audio, uid, title, artist)
                self.assertEqual(doc["kind"], "cache")
                self.assertTrue(doc["lines"])
            finally:
                LRF.LYRICS = old_lyrics
                LIB.LY.set_cache_dir(Path.home() / "Documents" / "momo_uta" / "data" / "cache" / "lyrics")


class TestBrokenV2Fallback(unittest.TestCase):
    def test_broken_v2_falls_back_to_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "歌手 - 曲.mp3"; audio.write_bytes(b"audio")
            cache = root / "cache"; cache.mkdir()
            LIB.LY.set_cache_dir(cache)
            old_lyrics = LRF.LYRICS
            LRF.LYRICS = root / "lyrics"
            try:
                title, artist = "曲", "歌手"
                LIB.LY.cache_path(title, artist).write_text(
                    json.dumps({"lrc": "[00:01.00]缓存\n[00:02.00]第二句\n[00:03.00]第三句",
                                "name": title, "artist": artist}), encoding="utf-8")
                uid = LIB.FP.fingerprint(audio)
                sp = LRF.store_path(audio, uid, title, artist)
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text("x\n#NHLRC 2\n{\"v\":2,\"lines\":[]}\n", encoding="utf-8")
                with patch.object(LRF, "parse_v2_rows", side_effect=ValueError("bad")):
                    doc = LRF.load(audio, uid, title, artist)
                self.assertEqual(doc["kind"], "cache")
                self.assertTrue(doc["lines"])
            finally:
                LRF.LYRICS = old_lyrics
                LIB.LY.set_cache_dir(Path.home() / "Documents" / "momo_uta" / "data" / "cache" / "lyrics")
