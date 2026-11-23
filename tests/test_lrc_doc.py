"""lrc_doc：纯格式层，不碰文件。"""
import unittest

from nihonco_player.core import lrc_doc as D


class TestLrcDoc(unittest.TestCase):
    def test_parse_keeps_drafts_and_metadata(self):
        rows, meta = D._parse_document("[ar:X]\n[00:05.00]词\n草稿\n")
        self.assertEqual([r["text"] for r in rows], ["词", "草稿"])
        self.assertIsNone(rows[1]["t"])
        self.assertEqual(meta[0]["before"], 0)

    def test_one_parser_keeps_blank_metadata_and_drafts_consistent(self):
        text = '[ar:X]\n[00:05.00]词\n\n草稿\n{"t":1234,"c":[{"tx":"あの日"}]}\n'
        rows, meta, body = D._parse_rows(text)
        self.assertEqual([r["text"] for r in rows], ["词", "草稿", "あの日"])
        self.assertEqual(meta[0]["before"], 0)
        self.assertEqual([r["text"] for r in body], ["词", "", "草稿", "あの日"])
        self.assertEqual(D.parse(text), rows)
        self.assertEqual(D._parse_body_rows(text), body)

    def test_timed_empty_line_keeps_body_position_but_not_compact(self):
        text = "[00:01.00]君\n[00:02.00]\n[00:03.00]花\n"
        rows, _meta, body = D._parse_rows(text)
        self.assertEqual([r["text"] for r in rows], ["君", "花"])
        self.assertEqual([r["text"] for r in body], ["君", "", "花"])
        self.assertEqual(body[1]["t"], 2.0)

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


class TestTranslations(unittest.TestCase):
    def test_nhlrc_roundtrip_translation(self):
        rows = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        text = D.render_nhlrc(rows, [], {0: [["君", "きみ", "A"]]},
                              {0: "你", 1: "花"})
        body, tail = D._split_nhlrc(text)
        self.assertEqual(D.translations_for(D.parse(body), tail), {0: "你", 1: "花"})

    def test_translation_only_still_writes_tail(self):
        rows = [{"t": 1.0, "text": "君"}]
        text = D.render_nhlrc(rows, [], None, {0: "你"}, "en")
        body, tail = D._split_nhlrc(text)
        self.assertIsNotNone(tail)
        self.assertEqual(tail["trans_lang"], "en")
        self.assertEqual(D.translations_for(D.parse(body), tail), {0: "你"})

    def test_align_translation_follows_text(self):
        old = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        new = [{"t": None, "text": "新增"}, {"t": 1.0, "text": "君"},
               {"t": 2.0, "text": "花"}]
        self.assertEqual(D.align_translations(new, old, {0: "你", 1: "花"}),
                         {1: "你", 2: "花"})

    def test_tlyric_timestamp_pairing(self):
        lines = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        self.assertEqual(D.translations_from_lrc(
            "[00:01.00]你\n[00:02.00]花\n", lines), {0: "你", 1: "花"})

    def test_tlyric_loose_timestamp(self):
        lines = [{"t": 1.0, "text": "君"}]
        self.assertEqual(D.translations_from_lrc("[00:01.10]你\n", lines), {0: "你"})

    def test_tlyric_order_fallback_only_when_counts_match(self):
        one = [{"t": 1.0, "text": "君"}]
        self.assertEqual(D.translations_from_lrc("[00:02.00]你\n", one), {0: "你"})
        two = [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "花"}]
        self.assertEqual(D.translations_from_lrc("[00:03.00]你\n", two), {})
