import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.build.aozora_parse import (       # noqa: E402
    parse, check, kata_to_hira)


class TestKana(unittest.TestCase):
    def test_kata_to_hira(self):
        self.assertEqual(kata_to_hira("カンジ"), "かんじ")
        self.assertEqual(kata_to_hira("コーヒー"), "こーひー")   # 长音符保留
        self.assertEqual(kata_to_hira("abc"), "abc")


class TestParse(unittest.TestCase):
    def test_implicit_kanji_base(self):
        text, spans = parse("今日《きょう》は良い天気です。")
        self.assertEqual(text, "今日は良い天気です。")
        self.assertEqual(spans, [{"start": 0, "end": 2, "base": "今日", "ruby": "きょう"}])

    def test_explicit_bar(self):
        text, spans = parse("物｜云《い》わぬ")
        self.assertEqual(text, "物云わぬ")
        self.assertEqual(spans, [{"start": 1, "end": 2, "base": "云", "ruby": "い"}])

    def test_katakana_ruby_becomes_hiragana(self):
        _, spans = parse("真鍮《シンチュウ》")
        self.assertEqual(spans[0]["ruby"], "しんちゅう")

    def test_notes_removed(self):
        text, spans = parse("彼は［＃「さう」はママ］言った。")
        self.assertEqual(text, "彼は言った。")
        self.assertEqual(spans, [])

    def test_gaiji_note_removed(self):
        text, _ = parse("※［＃「木＋吶のつくり」、第3水準1-85-54］の木")
        self.assertEqual(text, "の木")

    def test_ruby_tag_normalized(self):
        src = "<ruby>漢字<rt>かんじ</rt></ruby>です"
        text, spans = parse(src)
        self.assertEqual(text, "漢字です")
        self.assertEqual(spans[0]["base"], "漢字")
        self.assertEqual(spans[0]["ruby"], "かんじ")

    def test_multiple_spans_positions(self):
        text, spans = parse("山《やま》と川《かわ》")
        self.assertEqual(text, "山と川")
        self.assertEqual(text[spans[0]["start"]:spans[0]["end"]], "山")
        self.assertEqual(text[spans[1]["start"]:spans[1]["end"]], "川")

    def test_invariant_check(self):
        text, spans = parse("今日《きょう》は")
        self.assertEqual(check(text, spans), [])

    def test_unclosed_ruby_is_literal(self):
        text, spans = parse("閉じてない《")
        self.assertEqual(spans, [])
        self.assertIn("《", text)

    def test_okurigana_left_in_plain(self):
        text, spans = parse("食《た》べる")
        self.assertEqual(text, "食べる")
        self.assertEqual(spans[0], {"start": 0, "end": 1, "base": "食", "ruby": "た"})


if __name__ == "__main__":
    unittest.main()
