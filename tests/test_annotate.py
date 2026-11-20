import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD = [sys.executable, "-m", "nihonco_yomi.annotate", "--stdio"]


def call(req: dict) -> dict:
    p = subprocess.run(
        CMD,
        input=json.dumps(req, ensure_ascii=False) + "\n",
        capture_output=True, text=True, timeout=20,
    )
    return json.loads(p.stdout.strip().splitlines()[0])


class TestAnnotateM0(unittest.TestCase):
    def test_contract_fields(self):
        r = call({"text": "今日は雨が降る", "layers": ["ruby"]})
        for k in ("version", "lines", "stats"):
            self.assertIn(k, r)
        self.assertIn("engine", r["version"])
        self.assertIn("dict", r["version"])

    def test_kanji_line_is_annotated_or_explicitly_abstained(self):
        """M0 时这里全是 C；接入词典后，含汉字的行要么给 A 带 ruby，要么给 C 带理由。"""
        r = call({"text": "今日は雨が降る"})
        segs = r["lines"][0]["segments"]
        self.assertTrue(any(s["level"] == "A" and s["ruby"] for s in segs))
        for s in segs:
            if s["level"] == "C":
                self.assertIn("code", s.get("reason") or {})

    def test_kana_line_is_k(self):
        r = call({"text": "きれいだね"})
        seg = r["lines"][0]["segments"][0]
        self.assertEqual(seg["level"], "K")
        self.assertIsNone(seg["ruby"])

    def test_multi_line_split(self):
        r = call({"text": "今日は\nきれいだ"})
        self.assertEqual(len(r["lines"]), 2)
        self.assertTrue(r["lines"][0]["segments"])          # 第一行有内容
        self.assertEqual(r["lines"][1]["segments"][0]["level"], "K")

    def test_empty_text(self):
        r = call({"text": ""})
        self.assertEqual(r["lines"][0]["segments"], [])
        self.assertEqual(r["stats"]["annotated"], 0)

    def test_bad_json_does_not_kill_service(self):
        p = subprocess.run(
            CMD,
            input="not json\n" + json.dumps({"text": "きれい"}) + "\n",
            capture_output=True, text=True, timeout=20,
        )
        lines = [l for l in p.stdout.strip().splitlines() if l]
        self.assertEqual(len(lines), 2)                 # 第一条是 error，第二条正常
        self.assertIn("error", json.loads(lines[0]))
        self.assertIn("lines", json.loads(lines[1]))

    def test_romaji_and_keys_layers(self):
        """罗马音与键位：同一份读音，两套写法。"""
        r = call({"text": "今日は", "layers": ["ruby", "romaji", "keys"]})
        self.assertEqual(r["romaji"]["text"], "kyou wa")
        self.assertEqual(r["keys"]["text"], "kyou ha")


class TestSurgicalAbstention(unittest.TestCase):
    """外科式弃权：只在「我们给的读音不是词典首选」时放弃。"""

    def _first(self, text):
        return call({"text": text})["lines"][0]["segments"][0]

    def test_multi_reading_word_is_not_a(self):
        """多音字（词典有多个读音）：标出来，但降级到 AB 或 B。"""
        seg = self._first("大人")
        self.assertIn(seg["level"], ("AB", "B"))
        self.assertEqual(seg["ruby"], "おとな")

    def test_okurigana_word_uses_word_level_reading(self):
        """降る 的片段只有「降=ふ」，词级判定要拿 ふる 去比，不能拿片段比。"""
        segs = call({"text": "朝が降る"})["lines"][0]["segments"]
        seg = next(s for s in segs if s["base"] == "降")
        self.assertIn(seg["level"], ("A", "AB", "B"))
        self.assertEqual(seg["ruby"], "ふ")


class TestGlossary(unittest.TestCase):
    def _first(self, text):
        return call({"text": text})["lines"][0]["segments"][0]

    def test_glossary_overrides_tokenizer(self):
        """人工词表（data/curated/glossary_lyrics.json）优先于分词器：私→わたし 而不是 わたくし。"""
        import importlib  # noqa: E402
        A = importlib.import_module("nihonco_yomi.annotate")
        A.load_tables()
        self.assertEqual(A.GLOSSARY.get("私"), "わたし")
        seg = self._first("私の声")
        self.assertEqual(seg["ruby"], "わたし")


if __name__ == "__main__":
    unittest.main()


class TestTokenizerConcurrency(unittest.TestCase):
    def test_parallel_annotations_do_not_share_tokenizer(self):
        """HTTP 是多线程的：Sudachi Tokenizer 不能并发使用。"""
        import importlib
        import threading
        A = importlib.import_module("nihonco_yomi.annotate")

        errs, outs = [], []
        lock = threading.Lock()

        def work():
            try:
                for _ in range(5):
                    out = A.annotate_line("今日は雨が降る", {})
                    with lock:
                        outs.append(json.dumps(out, ensure_ascii=False, sort_keys=True))
            except Exception as e:      # noqa: BLE001
                with lock:
                    errs.append(repr(e))

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errs, errs[:3])
        self.assertEqual(len(set(outs)), 1)


if __name__ == "__main__":
    unittest.main()
