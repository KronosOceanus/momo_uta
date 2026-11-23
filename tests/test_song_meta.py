"""song_meta：offset 按歌曲 uid 存。"""
import json
import tempfile
import unittest
from pathlib import Path

from momo_player.core import song_meta as META


class TestSongMeta(unittest.TestCase):
    def test_offset_is_keyed_by_uid(self):
        old = META.FILE
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "song_meta.json"
            META.set_file(p)
            try:
                META.put("uid-a", offset=0.4)
                self.assertEqual(META.get("uid-a", "offset"), 0.4)
                self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                                 {"uid-a": {"offset": 0.4}})
            finally:
                META.set_file(old)


if __name__ == "__main__":
    unittest.main()
