"""歌词数据层：LRC 解析、匹配规则、打分、语言判定。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from nihonco_player.core import lyrics as L  # noqa: E402


class TestParseLrc(unittest.TestCase):
    def test_basic(self):
        rows = L.parse_lrc("[00:12.34]あの日\n[00:15.00]今も")
        self.assertEqual([r["t"] for r in rows], [12.34, 15.0])
        self.assertEqual(rows[0]["text"], "あの日")

    def test_netease_marker(self):
        """网易云会给非歌词行加 -1 后缀，不能因此整行丢掉。"""
        rows = L.parse_lrc("[00:00.00-1] 作词 : X\n[00:12.30] あの日")
        self.assertEqual(len(rows), 2)

    def test_sorted_and_skipped(self):
        rows = L.parse_lrc("[00:20.00]b\n[00:10.00]a\n不是时间行")
        self.assertEqual([r["text"] for r in rows], ["a", "b"])

    def test_content_lines_excludes_metadata(self):
        lrc = "[00:00.00]作词 : X\n[00:10.00]あの日\n[00:12.00]今も\n[00:14.00]空を"
        self.assertEqual(L.content_lines(lrc), 3)


class TestMatch(unittest.TestCase):
    def test_same(self):
        self.assertTrue(L._match("オレンジ", "オレンジ"))

    def test_suffix_tolerated(self):
        self.assertTrue(L._match("打上花火", "打上花火 (Cover)"))
        self.assertTrue(L._match("君の名は", "君の名は。"))

    def test_different_song_rejected(self):
        self.assertFalse(L._match("愛唄", "バレンタイン・キッス"))

    def test_short_title_not_substring(self):
        """3 字以内不做包含匹配，否则 レイン 会命中 ドット・ブレイン。"""
        self.assertFalse(L._match("レイン", "ドット・ブレイン"))


class TestScore(unittest.TestCase):
    def test_duration_close_scores_higher(self):
        a = {"name": "X", "artist": "A", "duration": 200}
        b = {"name": "X", "artist": "A", "duration": 320}
        self.assertGreater(L.score_candidate(a, "X", "A", 201),
                           L.score_candidate(b, "X", "A", 201))

    def test_title_mismatch_loses_points(self):
        c = {"name": "別の歌", "artist": "A", "duration": 200}
        self.assertLess(L.score_candidate(c, "X", "A", 200),
                        L.score_candidate({"name": "X", "artist": "A", "duration": 200}, "X", "A", 200))


class TestLangAndExclude(unittest.TestCase):
    def test_lang_guess(self):
        ja, _ = L.lang_guess("あの日見渡した渚を歩いた今も思い出すんだ君の後ろ姿")
        self.assertEqual(ja, "ja")
        zh, _ = L.lang_guess("我们曾经并肩走过那片沙滩那些日子再也不会回来了")
        self.assertEqual(zh, "other")

    def test_exclude_patterns(self):
        self.assertTrue(L.is_excluded("愛唄 -Instrumental-"))
        self.assertTrue(L.is_excluded("打上花火 カラオケ"))
        self.assertFalse(L.is_excluded("打上花火"))


if __name__ == "__main__":
    unittest.main()
