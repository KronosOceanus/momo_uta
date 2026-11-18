"""校验器与对齐：允许的输入必须过，已知的坏切分必须被拒。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import nihonco_yomi.invariants as IV  # noqa: E402


def seg(base, ruby, start, end, level="A"):
    return {"base": base, "ruby": ruby, "start": start, "end": end, "level": level}


class TestInvariants(unittest.TestCase):
    def test_clean_line_passes(self):
        line = "食べる"
        segs = [seg("食", "た", 0, 1), seg("べる", None, 1, 3, "K")]
        self.assertEqual(IV.check_line(line, segs), [])

    def test_reading_mismatch_caught_by_i1(self):
        segs = [seg("食", "く", 0, 2)]
        codes = [b["code"] for b in IV.check_line("食べ", segs)]
        self.assertIn("I1", codes)

    def test_okurigana_is_checked_at_split_time(self):
        """送り仮名对齐由 split_pieces 的 DP 保证：对不上就返回 None。"""
        import importlib  # noqa: E402
        A = importlib.import_module("nihonco_yomi.annotate")
        A.load_tables()
        self.assertIsNone(A.split_pieces("行う", "いき"))

    def test_short_reading_caught_by_i7(self):
        # 恋煩 → こ：读音对、边界错（DP 之前的贪心失败）
        segs = [seg("恋煩", "こ", 0, 2)]
        codes = [b["code"] for b in IV.check_line("恋煩", segs)]
        self.assertIn("I7", codes)

    def test_kana_with_ruby_caught_by_i5(self):
        segs = [seg("は", "わ", 0, 1)]
        self.assertIn("I5", [b["code"] for b in IV.check_line("は", segs)])

    def test_numeral_ruby_allowed(self):
        segs = [seg("8", "はち", 0, 1)]
        self.assertNotIn("I5", [b["code"] for b in IV.check_line("8", segs)])


class TestAlignment(unittest.TestCase):
    def setUp(self):
        import importlib  # noqa: E402
        A = importlib.import_module("nihonco_yomi.annotate")
        A.load_tables()
        self.A = A

    def test_greedy_would_fail_but_dp_succeeds(self):
        # こいわずらい 里「い」出现两次，贪心会切出 (恋煩,こ)
        pieces = self.A.split_pieces("恋煩い", "こいわずらい")
        self.assertEqual(pieces, [("恋煩", "こいわずら"), ("い", None)])

    def test_okurigana_boundary(self):
        self.assertEqual(self.A.split_pieces("食べる", "たべる"), [("食", "た"), ("べる", None)])

    def test_whole_word(self):
        self.assertEqual(self.A.split_pieces("大人", "おとな"), [("大人", "おとな")])


class TestEmitPolicy(unittest.TestCase):
    def test_emit_a_suppresses_ab_and_b(self):
        import importlib  # noqa: E402
        A = importlib.import_module("nihonco_yomi.annotate")
        A.load_tables()
        A.CONFIG.emit = "A"
        try:
            segs = A.annotate_line("大人と子供", {})["segments"]
        finally:
            A.CONFIG.emit = "B"
        ab = [s for s in segs if s["base"] == "大人"][0]
        a = [s for s in segs if s["base"] == "子供"][0]
        self.assertIsNone(ab["ruby"])
        self.assertTrue(ab.get("suppressed"))
        self.assertEqual(a["ruby"], "こども")


if __name__ == "__main__":
    unittest.main()
