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
