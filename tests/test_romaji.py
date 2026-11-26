"""罗马音 / 键位：表覆盖 + 四条上下文规则 + 往返自检。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from momo_yomi.romaji import KEYS, ROMAJI, keys_of, morae, romaji_of  # noqa: E402


class TestTables(unittest.TestCase):
    def test_romaji_and_keys_cover_same_units(self):
        gap = set(ROMAJI) ^ set(KEYS)
        # ん / を 写法不同但都存在；只允许"罗马音有、键位没有"的罕见拗音
        missing = {k for k in gap if k not in KEYS}
        self.assertEqual(missing, set(), f"键位表缺：{missing}")


class TestRomaji(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(romaji_of("こんにちは"), "konnichiha")
        self.assertEqual(romaji_of("がっこう"), "gakkou")
        self.assertEqual(romaji_of("まっちゃ"), "matcha")

    def test_orthographic(self):
        """完全逐字转写：おう 写 ou，长音符 ー 写 -。"""
        self.assertEqual(romaji_of("きょう"), "kyou")
        self.assertEqual(romaji_of("とうきょう"), "toukyou")
        self.assertEqual(romaji_of("ひろう"), "hirou")
        self.assertEqual(romaji_of("コーヒー"), "ko-hi-")

    def test_particle_only_when_pos_says_so(self):
        self.assertEqual(romaji_of("は", particle=True), "wa")
        self.assertEqual(romaji_of("は", particle=False), "ha")
        self.assertEqual(romaji_of("へ", particle=True), "e")
        self.assertEqual(romaji_of("を", particle=True), "o")

    def test_n(self):
        self.assertEqual(romaji_of("しんいち"), "shinichi")   # 罗马音不加撇号
        self.assertEqual(romaji_of("ほん"), "hon")

    def test_ji_zu_modern(self):
        self.assertEqual(romaji_of("ぢめん"), "jimen")
        self.assertEqual(romaji_of("つづく"), "tsuzuku")

    def test_small_ke_and_v_rows(self):
        self.assertEqual(romaji_of("ゔぁ"), "va")
        self.assertEqual(keys_of("ゔぁ"), "va")
        self.assertEqual(romaji_of("ヶ"), "ka")
        self.assertEqual(romaji_of("ヵ"), "ka")
        self.assertEqual(keys_of("ヶ"), "ka")
        self.assertEqual(morae("ゔぁ"), ["ゔぁ"])


class TestKeys(unittest.TestCase):
    def test_particles_are_typed_literally(self):
        self.assertEqual(keys_of("は"), "ha")
        self.assertEqual(keys_of("を"), "wo")
        self.assertEqual(keys_of("へ"), "he")

    def test_n_apostrophe_before_vowel(self):
        self.assertEqual(keys_of("しんいち"), "shin'ichi")
        self.assertEqual(keys_of("こんや"), "kon'ya")
        self.assertEqual(keys_of("ほん"), "hon")

    def test_sokuon_and_long_mark(self):
        self.assertEqual(keys_of("がっこう"), "gakkou")
        self.assertEqual(keys_of("まっちゃ"), "matcha")
        self.assertEqual(keys_of("コーヒー"), "ko-hi-")


class TestMorae(unittest.TestCase):
    def test_youon_is_one_unit(self):
        self.assertEqual(morae("きょう"), ["きょ", "う"])
        self.assertEqual(morae("しゃしん"), ["しゃ", "し", "ん"])


class RoundTrip(unittest.TestCase):
    """独立实现的贪心解析器：把键位还原成假名。用来验证生成没跑偏。"""

    @staticmethod
    def parse(text: str) -> str:
        table = {v: k for k, v in KEYS.items() if v not in ("n'", "nn")}
        table["-"] = "ー"
        out, i, sokuon = [], 0, False
        while i < len(text):
            if text[i] == "'":
                i += 1
                continue
            for size in (3, 2, 1):
                chunk = text[i:i + size]
                if chunk in table:
                    kana = table[chunk]
                    out.append("っ" + kana if sokuon else kana)
                    sokuon = False
                    i += size
                    break
            else:
                ch = text[i]
                if ch == "n":
                    out.append("ん")
                    i += 1
                else:                      # 促音：下一个辅音双写
                    sokuon = True
                    i += 1
                continue
        return "".join(out)

    def test_roundtrip(self):
        for kana in ("がっこう", "まっちゃ", "ともだち", "きょう", "しんいち", "つづく"):
            keys = keys_of(kana)
            self.assertEqual(self.parse(keys), kana, f"{kana} → {keys}")


if __name__ == "__main__":
    unittest.main()
