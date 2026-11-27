"""lrc_doc：纯格式层，不碰文件。"""
import unittest

from momo_player.core import lrc_doc as D


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

    def test_timed_empty_line_keeps_body_position_but_not_compact(self):
        text = "[00:01.00]君\n[00:02.00]\n[00:03.00]花\n"
        rows, _meta, body = D._parse_rows(text)
        self.assertEqual([r["text"] for r in rows], ["君", "花"])
        self.assertEqual([r["text"] for r in body], ["君", "", "花"])
        self.assertEqual(body[1]["t"], 2.0)

    def test_parse_netease_json(self):
        rows = D.parse('{"t":1234,"c":[{"tx":"あの日"}]}\n')
        self.assertEqual(rows, [{"t": 1.23, "text": "あの日"}])

    def test_credit_lines_are_metadata_and_keep_body_timestamp(self):
        self.assertTrue(D.is_metadata_text("作詞: 星野源"))
        self.assertTrue(D.is_metadata_text("[ar:X]作詞: Y"))
        self.assertTrue(D.is_metadata_text("[ar:X]hello"))
        self.assertTrue(D.is_metadata_text("Lyrics by: X"))
        self.assertTrue(D.is_metadata_text("Produced by: X"))
        self.assertFalse(D.is_metadata_text("作詞の歌を歌う"))
        rows, meta, body = D._parse_rows(
            "[00:00.00]作詞: 星野源\n[00:10.00]君\n")
        self.assertEqual([r["text"] for r in rows], ["君"])
        self.assertEqual([r["text"] for r in body], ["作詞: 星野源", "君"])
        self.assertEqual(body[0]["t"], 0.0)
        self.assertEqual(meta, [])

    def test_render_roundtrip(self):
        rows = [{"t": 5.0, "text": "君"}, {"t": None, "text": "草稿"}]
        text = D.render(rows, [{"before": 0, "text": "[ar:X]"}])
        self.assertTrue(text.startswith("[ar:X]\n[00:05.00]君\n草稿\n"))

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
