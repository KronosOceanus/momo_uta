"""LRC API：已有 nhlrc 时更新必须带版本。"""
import unittest
from unittest.mock import patch

from momo_player.service import lrc as SVC_LRC


class TestLrcApiVersion(unittest.TestCase):
    def setUp(self):
        self.item = {"uid": "u0", "file": "/tmp/x.mp3", "title": "x", "artist": "", "key": "k"}

    def test_save_rows_without_version_is_rejected_when_document_exists(self):
        with patch.object(SVC_LRC.LIB, "resolve", return_value=self.item), \
             patch.object(SVC_LRC.LRC, "current_version", return_value="v1"), \
             patch.object(SVC_LRC.LD, "save_rows") as save:
            res = SVC_LRC.lrc_action({"action": "save_rows", "uid": "u0", "rows": []})
        self.assertFalse(res["ok"])
        self.assertTrue(res["conflict"])
        self.assertEqual(res["version"], "v1")
        save.assert_not_called()

    def test_save_rows_without_version_is_allowed_for_new_document(self):
        with patch.object(SVC_LRC.LIB, "resolve", return_value=self.item), \
             patch.object(SVC_LRC.LRC, "current_version", return_value=None), \
             patch.object(SVC_LRC.LD, "save_rows", return_value={"ok": True}) as save:
            res = SVC_LRC.lrc_action({"action": "save_rows", "uid": "u0", "rows": []})
        self.assertTrue(res["ok"])
        save.assert_called_once()

    def test_destructive_actions_without_version_are_rejected(self):
        for action in ("import_lrc", "restore", "delete"):
            with self.subTest(action=action), \
                 patch.object(SVC_LRC.LIB, "resolve", return_value=self.item), \
                 patch.object(SVC_LRC.LRC, "current_version", return_value="v1"), \
                 patch.object(SVC_LRC, "save_lyrics") as save:
                res = SVC_LRC.lrc_action({"action": action, "uid": "u0", "text": "x"})
            self.assertFalse(res["ok"])
            self.assertTrue(res["conflict"])
            save.assert_not_called()

    def test_import_lrc_without_version_is_allowed_for_new_document(self):
        with patch.object(SVC_LRC.LIB, "resolve", return_value=self.item), \
             patch.object(SVC_LRC.LRC, "current_version", return_value=None), \
             patch.object(SVC_LRC, "save_lyrics", return_value={"ok": True}) as save:
            res = SVC_LRC.lrc_action({"action": "import_lrc", "uid": "u0", "text": "x"})
        self.assertTrue(res["ok"])
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
