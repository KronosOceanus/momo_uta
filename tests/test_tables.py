"""数据表回归：钉住几条关键事实，防止重建表时静默退化。

这些都是"曾经出过 bug 或人工纠偏过"的条目。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "data" / "tables"
CORPUS = ROOT / "data" / "corpus"
CURATED = ROOT / "data" / "curated"


def load(name, where=None):
    p = (where or TABLES) / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class TestTables(unittest.TestCase):
    def test_heteronym(self):
        t = load("jmdict_heteronym.json")
        self.assertTrue(t, "jmdict_heteronym.json 不存在")
        self.assertGreater(len(t.get("胆", [])), 1)

    def test_glossary_present(self):
        t = load("glossary_lyrics.json", CURATED)
        self.assertTrue(t, "data/curated/glossary_lyrics.json 不存在")
        self.assertEqual(t.get("私"), "わたし")

    def test_resource_present(self):
        t = load("utaten_resource.json", CORPUS)
        if t is None:
            self.skipTest("没有语料表（没跑过 make build-resource）")
        self.assertGreater(len(t), 500)

    def test_readings_shape(self):
        t = load("jmdict_readings.json")
        self.assertTrue(t, "jmdict_readings.json 不存在")
        self.assertIn("いち", t.get("一", []))
        self.assertTrue(all(isinstance(v, list) for v in list(t.values())[:100]))


if __name__ == "__main__":
    unittest.main()
