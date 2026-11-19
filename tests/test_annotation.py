"""注音装配：括号注音、手改读音、nhlrc 标注对齐。"""
import unittest

from nihonco_player.core import annotation as A


class TestAnnotation(unittest.TestCase):
    def test_strip_paren_ruby(self):
        clean, notes = A.strip_paren_ruby("笑顔(かお)で")
        self.assertEqual(clean, "笑顔で")
        self.assertEqual(notes, {0: "かお"})

    def test_manual_reading_overrides_engine(self):
        r = A.annotate_line_with_notes("君の名前", extra_start=0, extra_reading="きみだ")
        self.assertIn("きみだ", A.ruby_html(r))
        self.assertIn("kimi", A.words_html_of(r, "romaji"))

    def test_line_fields_shape(self):
        f = A.line_fields("君の名前")
        self.assertEqual(set(f), {"ruby", "rm", "ky", "rmH", "kyH"})
        self.assertIn("kimi", f["rm"])
        self.assertIn("<ruby", f["ruby"])

    def test_stored_segments_match_engine(self):
        clean, _ = A.strip_paren_ruby("君の名前")
        segs = A.AN.annotate(clean)["lines"][0]["segments"]
        stored = A.segs_of(A.annotate_line_with_notes("君の名前"))
        self.assertIsNotNone(A._stored_overrides(clean, segs, stored))
        r = A.annotate_line_with_notes("君の名前", stored=stored)
        self.assertIn("きみ", A.ruby_html(r))

    def test_stored_segments_mismatch_returns_none(self):
        clean, _ = A.strip_paren_ruby("君の名前")
        segs = A.AN.annotate(clean)["lines"][0]["segments"]
        self.assertIsNone(A._stored_overrides(clean, segs, [["别人", "べつ", "A"]]))

    def test_annotations_from_lines_skips_empty(self):
        out = A.annotations_from_lines([{"text": "君"}, {"text": "  "}])
        self.assertEqual(sorted(out), [0])
        self.assertEqual("".join(x[0] for x in out[0]), "君")


if __name__ == "__main__":
    unittest.main()
