"""lrc_doc：纯格式层，不碰文件。"""
import unittest

from nihonco_player.core import lrc_doc as D


class TestLrcDoc(unittest.TestCase):
    def test_parse_keeps_drafts_and_metadata(self):
        rows, meta = D._parse_document("[ar:X]\n[00:05.00]词\n草稿\n")
        self.assertEqual([r["text"] for r in rows], ["词", "草稿"])
        self.assertIsNone(rows[1]["t"])
        self.assertEqual(meta[0]["before"], 0)

    def test_parse_netease_json(self):
        rows = D.parse('{"t":1234,"c":[{"tx":"あの日"}]}\n')
        self.assertEqual(rows, [{"t": 1.23, "text": "あの日"}])

    def test_render_roundtrip(self):
        rows = [{"t": 5.0, "text": "君"}, {"t": None, "text": "草稿"}]
        text = D.render(rows, [{"before": 0, "text": "[ar:X]"}])
        self.assertTrue(text.startswith("[ar:X]\n[00:05.00]君\n草稿\n"))

    def test_nhlrc_body_and_annotation(self):
        rows = [{"t": 1.0, "text": "君"}]
        text = D.render_nhlrc(rows, [], {0: [["君", "きみ", "A"]]})
        body, tail = D._split_nhlrc(text)
        self.assertEqual(body, "[00:01.00]君\n")
        self.assertEqual(D.annotations_for(rows, tail), {0: [["君", "きみ", "A"]]})

    def test_bad_tail_is_ignored(self):
        text = "[00:01.00]君\n\n#NHLRC 1\n{not json}\n"
        body, tail = D._split_nhlrc(text)
        self.assertEqual(tail, None)
        self.assertEqual(D.annotations_for([{"t": 1.0, "text": "君"}], tail), {})


if __name__ == "__main__":
    unittest.main()


class TestTailFormat(unittest.TestCase):
    def test_one_entry_per_line(self):
        rows = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        text = D.render_nhlrc(rows, [], {0: [["君", "きみ", "A"]],
                                         1: [["花", "はな", "A"]]})
        tail_lines = [ln for ln in text.splitlines() if '"i":' in ln]
        self.assertEqual(len(tail_lines), 2)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.strip().startswith("{")) >= 2, True)

    def test_body_hash_fast_path_skips_line_hash(self):
        rows = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        text = D.render_nhlrc(rows, [], {0: [["君", "きみ", "A"]],
                                         1: [["花", "はな", "A"]]})
        body, tail = D._split_nhlrc(text)
        for ent in tail["lines"]:
            ent["h"] = "deadbeef"                 # 行哈希故意写错
        self.assertEqual(len(D.annotations_for(D.parse(body), tail, strict=True)), 0)
        self.assertEqual(len(D.annotations_for(D.parse(body), tail, strict=False)), 2)

    def test_body_mismatch_falls_back_to_line_hash(self):
        rows = [{"t": 1.0, "text": "君"}]
        text = D.render_nhlrc(rows, [], {0: [["君", "きみ", "A"]]})
        body, tail = D._split_nhlrc(text)
        tail["body"] = "00000000"
        tail["lines"][0]["h"] = "00000000"
        self.assertEqual(D.annotations_for(D.parse(body), tail, strict=True), {})
