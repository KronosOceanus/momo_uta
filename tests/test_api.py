"""对外接口：Annotator / annotate 的形状与稳定性。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from momo_yomi import Annotator  # noqa: E402


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.an = Annotator()

    def test_three_layers(self):
        r = self.an.annotate("今日は")
        self.assertEqual(r["romaji"]["text"], "kyou wa")
        self.assertEqual(r["keys"]["text"], "kyou ha")
        self.assertEqual(self.an.reading("今日は"), "きょうは")

    def test_particles_and_numbers(self):
        r = self.an.annotate("コーヒーを飲んだ")
        self.assertEqual(r["romaji"]["text"], "ko-hi- o nonda")

    def test_lines_shape(self):
        r = self.an.annotate("東京\n大阪")
        self.assertEqual(len(r["lines"]), 2)
        for line in r["lines"]:
            for seg in line["segments"]:
                self.assertIn("base", seg)
                self.assertIn(seg["level"], ("A", "AB", "B", "C", "K"))


if __name__ == "__main__":
    unittest.main()
