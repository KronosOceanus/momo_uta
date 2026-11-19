import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.eval.evalkit as evalkit        # noqa: E402
from tools.common import normalize           # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_katakana_to_hiragana(self):
        self.assertEqual(normalize("カンジ"), "かんじ")

    def test_fullwidth_to_halfwidth(self):
        self.assertEqual(normalize("ＡＢＣ"), "ABC")

    def test_keeps_long_vowel(self):
        self.assertEqual(normalize("コーヒー"), "こーひー")


class TestPredictedSpans(unittest.TestCase):
    def test_flattens_lines(self):
        resp = {"lines": [{"segments": [{"ruby": "あ"}, {"ruby": None}]},
                          {"segments": [{"ruby": "い"}]}]}
        self.assertEqual(len(evalkit.predicted_spans(resp)), 2)

    def test_accepts_flat_segments(self):
        resp = {"segments": [{"ruby": "あ"}, {"ruby": None}]}
        self.assertEqual(len(evalkit.predicted_spans(resp)), 1)


class TestScore(unittest.TestCase):
    """用一个假标注器验证打分口径：对/错/漏/溢出怎么算。"""

    def _gold(self):
        return [{
            "text": "土産を買った", "primary": "R4", "domain": "lyrics",
            "spans": [{"start": 0, "end": 2, "base": "土産", "ruby": "みやげ"}],
        }]

    def test_correct(self):
        def ann(text):
            return {"lines": [{"segments": [
                {"base": "土産", "start": 0, "end": 2, "ruby": "みやげ"}]}]}
        res = evalkit.score(self._gold(), ann)
        self.assertEqual(res["totals"]["correct"], 1)
        self.assertEqual(res["totals"]["wrong"], 0)
        self.assertEqual(res["report"]["precision"], "100.0%")

    def test_wrong_reading(self):
        def ann(text):
            return {"lines": [{"segments": [
                {"base": "土産", "start": 0, "end": 2, "ruby": "どさん"}]}]}
        res = evalkit.score(self._gold(), ann)
        self.assertEqual(res["totals"]["wrong"], 1)
        self.assertEqual(res["totals"]["correct"], 0)

    def test_miss(self):
        def ann(text):
            return {"lines": [{"segments": [{"base": "土産", "start": 0, "end": 2, "ruby": None}]}]}
        res = evalkit.score(self._gold(), ann)
        self.assertEqual(res["totals"]["miss"], 1)

    def test_extra_counted_separately(self):
        def ann(text):
            return {"lines": [{"segments": [
                {"base": "土産", "start": 0, "end": 2, "ruby": "みやげ"},
                {"base": "買", "start": 3, "end": 4, "ruby": "か"}]}]}
        res = evalkit.score(self._gold(), ann)
        self.assertEqual(res["totals"]["extra"], 1)
        self.assertEqual(res["totals"]["correct"], 1)      # 溢出不进 precision 分母


class TestMergeSpans(unittest.TestCase):
    def test_split_segments_merge_to_one_reading(self):
        """掃除+機 两段拼起来应等于 gold 的一个 span。"""
        gold = [{"text": "掃除機", "primary": "R12", "domain": "prose",
                 "spans": [{"start": 0, "end": 3, "base": "掃除機", "ruby": "そうじき"}]}]

        def ann(text):
            return {"lines": [{"segments": [
                {"base": "掃除", "start": 0, "end": 2, "ruby": "そうじ"},
                {"base": "機", "start": 2, "end": 3, "ruby": "き"}]}]}
        res = evalkit.score(gold, ann)
        self.assertEqual(res["totals"]["correct"], 1)


if __name__ == "__main__":
    unittest.main()
