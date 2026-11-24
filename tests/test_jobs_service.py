"""service/jobs：vocals / match / rebuild 的统一任务入口。"""
import time
import unittest
from unittest.mock import patch

from momo_player.core import jobs as JOBS
from momo_player.core import library as LIB
from momo_player.core import vocals as VOC
from momo_player.core.library import CACHE
from momo_player.service import jobs as SJ
from momo_player.service import song as SONG


def wait(job_id, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        job = JOBS.get(job_id)
        if job and job["state"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job timeout")


class TestJobService(unittest.TestCase):
    def setUp(self):
        self.old = dict(CACHE)
        CACHE.clear()
        CACHE["0"] = {"uid": "u-test", "file": "/tmp/x.mp3", "title": "x",
                      "artist": "a", "key": "k", "has_lyric": False}
        LIB.BY_UID["u-test"] = CACHE["0"]

    def tearDown(self):
        CACHE.clear()
        CACHE.update(self.old)

    def test_match_job(self):
        with patch.object(SONG, "lazy_match") as lazy:
            job = SJ.start("match", "u-test")
            done = wait(job["id"])
        lazy.assert_called_once()
        self.assertEqual(done["state"], "done")

    def test_vocals_job(self):
        with patch.object(VOC, "ensure", return_value={"state": "queued"}), \
             patch.object(VOC, "status", return_value={"state": "done", "has_vocals": True}):
            job = SJ.start("vocals", "u-test")
            done = wait(job["id"])
        self.assertEqual(done["result"]["has_vocals"], True)

    def test_rebuild_job(self):
        old_missing = LIB.LAST_MISSING
        LIB.LAST_MISSING = ["u-test"]
        try:
            with patch.object(LIB, "rebuild_library", return_value={"ok": True, "recovered": 1}):
                job = SJ.start("rebuild")
                done = wait(job["id"])
            self.assertEqual(done["result"]["recovered"], 1)
        finally:
            LIB.LAST_MISSING = old_missing

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            SJ.start("nope", "u-test")


if __name__ == "__main__":
    unittest.main()


class TestVocalsBusy(unittest.TestCase):
    def test_vocals_over_limit_is_busy(self):
        from momo_player.core import jobs as J
        old = J._jobs.copy()
        old_cache = dict(CACHE)
        try:
            CACHE.clear()
            CACHE["0"] = {"uid": "u-test", "file": "/tmp/x.mp3", "title": "x",
                          "artist": "a", "key": "k", "has_lyric": False}
            LIB.BY_UID["u-test"] = CACHE["0"]
            J._jobs.update({
                "a": {"id": "a", "kind": "vocals", "key": "a", "state": "queued"},
                "b": {"id": "b", "kind": "vocals", "key": "b", "state": "canceling"},
            })
            with patch.object(SJ, "MAX_ACTIVE_VOCALS", 2):
                with self.assertRaises(SJ.JobBusy):
                    SJ.start("vocals", "u-test")
        finally:
            J._jobs.clear(); J._jobs.update(old)
            CACHE.clear(); CACHE.update(old_cache)
