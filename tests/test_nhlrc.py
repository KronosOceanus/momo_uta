"""nhlrc：正文 + 尾部假名标注的读写与校验。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nihonco_player.core import lrc_doc as DOC
from nihonco_player.core import lrc_files as LRF


def rows():
    return [{"t": 5.0, "text": "君の名前"}, {"t": 9.0, "text": "呼んでくれた"}]


class TestNhlrc(unittest.TestCase):
    def test_roundtrip_body_and_annotations(self):
        ann = {0: [["君", "きみ", "A"], ["の", None, None], ["名前", "なまえ", "B"]],
               1: [["呼んでくれた", None, None]]}
        text = DOC.render_nhlrc(rows(), [], ann)
        self.assertIn("#NHLRC 1", text)
        body, tail = DOC._split_nhlrc(text)
        self.assertTrue(body.startswith("[00:05.00]君の名前"))
        self.assertEqual(DOC.annotations_for(rows(), tail), ann)

    def test_line_and_token_ids_roundtrip(self):
        ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]}
        lids = {0: "l_00112233"}
        tids = {0: ["t_44556677", "t_8899aabb"]}
        text = DOC.render_nhlrc(rows(), [], ann, line_ids=lids, token_ids=tids)
        self.assertIn('"lid": "l_00112233"', text)
        self.assertIn('"tid": ["t_44556677","t_8899aabb"]', text)
        _body, tail = DOC._split_nhlrc(text)
        got_ann, got_lids, got_tids = DOC.annotations_and_ids_for(rows(), tail)
        self.assertEqual(got_ann, ann)
        self.assertEqual(got_lids, lids)
        self.assertEqual(got_tids, tids)

    def test_missing_ids_get_stable_legacy_ids(self):
        text = DOC.render_nhlrc(rows(), [], {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]})
        _body, tail = DOC._split_nhlrc(text)
        first = DOC.annotations_and_ids_for(rows(), tail)
        second = DOC.annotations_and_ids_for(rows(), tail)
        self.assertEqual(first, second)
        self.assertRegex(first[1][0], r"^l_[0-9a-f]{8}$")
        self.assertRegex(first[2][0][0], r"^t_[0-9a-f]{8}$")

    def test_duplicate_tid_inside_one_line_is_replaced(self):
        text = DOC.render_nhlrc([{"t": 1.0, "text": "君"}], [],
                                {0: [["君", "きみ", "A"]]},
                                line_ids={0: "l_00112233"},
                                token_ids={0: ["t_44556677", "t_44556677"]})
        _body, tail = DOC._split_nhlrc(text)
        self.assertIn('"tid"', text)
        _ann, lids, tids = DOC.annotations_and_ids_for([{"t": 1.0, "text": "君"}], tail)
        self.assertTrue(lids)
        self.assertEqual(len(tids[0]), 1)
        self.assertRegex(tids[0][0], r"^t_[0-9a-f]{8}$")

    def test_one_invalid_tid_does_not_drop_the_other_tokens(self):
        ann = {0: [["君", "きみ", "A"], ["の", "の", "K"]]}
        text = DOC.render_nhlrc([{"t": 1.0, "text": "君の"}], [], ann,
                                line_ids={0: "l_00112233"},
                                token_ids={0: ["t_44556677", "not-an-id"]})
        _body, tail = DOC._split_nhlrc(text)
        _ann, _lids, tids = DOC.annotations_and_ids_for(
            [{"t": 1.0, "text": "君の"}], tail)
        self.assertEqual(tids[0][0], "t_44556677")
        self.assertRegex(tids[0][1], r"^t_[0-9a-f]{8}$")
        self.assertNotEqual(tids[0][0], tids[0][1])

    def test_duplicate_ids_are_replaced_when_writing(self):
        ann = {0: [["君", "きみ", "A"]], 1: [["の", "の", "K"]]}
        lids = {0: "l_00112233", 1: "l_00112233"}
        tids = {0: ["t_44556677"], 1: ["t_44556677"]}
        text = DOC.render_nhlrc([{"t": 1.0, "text": "君"},
                                 {"t": 2.0, "text": "の"}], [], ann,
                                line_ids=lids, token_ids=tids)
        _body, tail = DOC._split_nhlrc(text)
        _ann, got_lids, got_tids = DOC.annotations_and_ids_for(
            [{"t": 1.0, "text": "君"}, {"t": 2.0, "text": "の"}], tail)
        self.assertEqual(len(got_lids), 2)
        self.assertEqual(len(set(got_lids.values())), 2)
        self.assertEqual(len(got_tids), 2)
        self.assertEqual(len(set(got_tids[0] + got_tids[1])), 2)

    def test_blank_body_row_does_not_shift_annotation_index(self):
        lines = [{"t": 5.0, "text": "君の名前"}, {"t": None, "text": ""},
                 {"t": 9.0, "text": "呼んでくれた"}]
        ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]],
               2: [["呼んでくれた", None, None]]}
        text = DOC.render_nhlrc(lines, [], ann, annotation_index={0: 0, 2: 1})
        body, tail = DOC._split_nhlrc(text)
        self.assertIn("[00:05.00]君の名前\n\n[00:09.00]呼んでくれた\n", body)
        parsed, _ = DOC._parse_document(body)
        self.assertEqual(len(parsed), 2)
        got = DOC.annotations_for(parsed, tail)
        self.assertEqual(got[0], ann[0])
        self.assertEqual(got[1], ann[2])
        rows = DOC._parse_body_rows(body)
        self.assertEqual([x["text"] for x in rows], ["君の名前", "", "呼んでくれた"])

    def test_annotation_dropped_when_text_changed(self):
        ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]}
        text = DOC.render_nhlrc(rows(), [], ann)
        _body, tail = DOC._split_nhlrc(text)
        changed = [{"t": 5.0, "text": "君のなまえ"}, {"t": 9.0, "text": "呼んでくれた"}]
        self.assertEqual(DOC.annotations_for(changed, tail), {})

    def test_annotation_dropped_when_bases_do_not_add_up(self):
        text = DOC.render_nhlrc(rows(), [], {0: [["君", "きみ", "A"]]})
        _body, tail = DOC._split_nhlrc(text)
        self.assertEqual(DOC.annotations_for(rows(), tail), {})

    def test_save_writes_nhlrc_and_keeps_body_lrc_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            ann = {0: [["君", "きみ", "A"], ["の名前", "のなまえ", "B"]]}
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                res = LRF.save(audio, rows(), ann)
                self.assertTrue(res["ok"])
                p = LRF.store_path(audio)
                self.assertTrue(p.is_file())
                raw = p.read_text(encoding="utf-8")
                self.assertTrue(raw.startswith("[00:05.00]君の名前"))
                self.assertIn("#NHLRC 1", raw)
                doc = LRF.load(audio)
                self.assertEqual(doc["annotations"], ann)
            self.assertEqual(DOC.render_body(rows(), []), "[00:05.00]君の名前\n[00:09.00]呼んでくれた\n")

    def test_backup_created_on_first_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "歌手 - 曲.mp3"
            audio.touch()
            with patch.object(LRF, "LYRICS", Path(tmp) / "lyrics"), \
                 patch.object(LRF.LY, "audio_duration", return_value=60):
                LRF.save(audio, rows())                 # 第一次：没有旧文件
                uid = LRF.uid_of(audio)
                first = LRF.store_path(audio).read_text(encoding="utf-8")
                LRF.save(audio, rows())                 # 第二次：备份第一次的内容
                self.assertEqual(LRF.backup_path(audio, uid).read_text(encoding="utf-8"), first)


if __name__ == "__main__":
    unittest.main()
