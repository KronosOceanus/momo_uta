"""歌词数据层：LRC 解析、匹配规则、打分、语言判定。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from momo_player.core import lyrics as L  # noqa: E402




class TestTimedLyrics(unittest.TestCase):
    def test_multiline_regex(self):
        self.assertTrue(L.has_timed("[00:00.000] a\n[00:12.212] b\n"))

    def test_untimed_rejected(self):
        self.assertFalse(L.has_timed("作词 : X\nあの日\n今も"))
        self.assertTrue(L.valid_lrc("[00:01.00]あの日\n[00:03.00]今も\n[00:05.00]空を"))
        self.assertFalse(L.valid_lrc("[00:01.00]あの日\n[00:03.00]今も"))


class TestLocalOnlyLoad(unittest.TestCase):
    def test_local_only_does_not_call_network(self):
        import tempfile
        from momo_player.core import lyrics_fetch as LF
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(LF, "cache_path", return_value=Path(tmp) / "none.json"), \
                 patch.object(LF, "auto_match", side_effect=AssertionError("不该联网")):
                self.assertIsNone(LF.get_lrc("曲", "歌手", network=False))


class TestSearchUsesPayload(unittest.TestCase):
    def test_search_uses_search_payload_without_detail(self):
        import json
        from momo_player.core import lyrics_fetch as LF
        payload = {"result": {"songs": [{
            "id": 94214994, "name": "群青",
            "artists": [{"name": "YOASOBI"}], "duration": 248444,
            "album": {"name": "群青"}}]}}
        with patch.object(LF, "_get", return_value=json.dumps(payload)) as get:
            out = LF.search_candidates("群青", "YOASOBI", limit=1)
        self.assertEqual(out[0]["id"], 94214994)
        self.assertEqual(out[0]["artist"], "YOASOBI")
        self.assertEqual(out[0]["duration"], 248.4)
        self.assertFalse(any("song/detail" in c.args[0] for c in get.call_args_list))


class TestUnifiedMatch(unittest.TestCase):
    def test_auto_skips_candidate_without_valid_lyrics(self):
        from momo_player.core import lyrics_fetch as LF
        c1 = {"id": 1, "name": "曲", "artist": "歌手", "duration": 60.0}
        c2 = {"id": 2, "name": "曲", "artist": "歌手", "duration": 60.0}
        hit = {"id": 2, "name": "曲", "lrc": "[00:01.00]あの日"}
        with patch.object(LF, "search_candidates", return_value=[c1, c2]), \
             patch.object(LF, "fetch_candidate", side_effect=[None, hit]):
            self.assertEqual(LF.auto_match("曲", "歌手", 60), hit)


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

class TestLyricsNetworkStatus(unittest.TestCase):
    def test_detail_network_error_does_not_write_negative_cache(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from momo_player.core import lyrics_fetch as LF

        c = {"id": 1, "name": "曲", "artist": "歌手", "duration": 60.0}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "miss.json"
            with patch.object(LF, "cache_path", return_value=p), \
                 patch.object(LF, "search_candidates_status", return_value=([c], LF.MATCH_OK)), \
                 patch.object(LF, "fetch_candidate", side_effect=LF.LyricsNetworkError("timeout")):
                hit, status = LF.get_lrc_status("曲", "歌手", use_cache=False,
                                                force=True, duration=60)
            self.assertIsNone(hit)
            self.assertEqual(status, LF.MATCH_NETWORK)
            self.assertFalse(p.exists())

    def test_empty_valid_response_still_reaches_no_lyrics(self):
        from unittest.mock import patch
        from momo_player.core import lyrics_fetch as LF

        c = {"id": 1, "name": "曲", "artist": "歌手", "duration": 60.0}
        with patch.object(LF, "search_candidates_status", return_value=([c], LF.MATCH_OK)), \
             patch.object(LF, "fetch_candidate", return_value=None):
            hit, status = LF.auto_match_status("曲", "歌手", 60)
        self.assertIsNone(hit)
        self.assertEqual(status, LF.MATCH_NO_LYRICS)

    def test_fetch_by_id_reports_network_error(self):
        from unittest.mock import patch
        from momo_player.core import lyrics_fetch as LF
        with patch.object(LF, "_get", side_effect=LF.LyricsNetworkError("down")):
            self.assertTrue(LF.fetch_lyrics_by_id(1).get("network_error"))
