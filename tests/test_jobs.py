"""统一任务表：状态、幂等、失败与结果。"""
import time
import unittest

from nihonco_player.core import jobs as JOBS


def wait(job_id, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        job = JOBS.get(job_id)
        if job and job["state"] in ("done", "failed", "canceled"):
            return job
        time.sleep(0.01)
    raise AssertionError("job timeout: " + str(JOBS.get(job_id)))


class TestJobs(unittest.TestCase):
    def test_success_result(self):
        job = JOBS.start("test", "ok", lambda: {"value": 1})
        done = wait(job["id"])
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result"], {"value": 1})

    def test_same_active_job_is_reused(self):
        def slow():
            time.sleep(0.2)
            return True
        a = JOBS.start("test", "same", slow)
        b = JOBS.start("test", "same", slow)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(wait(a["id"])["state"], "done")

    def test_failure_records_error(self):
        def boom():
            raise RuntimeError("nope")
        job = JOBS.start("test", "fail", boom)
        done = wait(job["id"])
        self.assertEqual(done["state"], "failed")
        self.assertIn("nope", done["error"])

    def test_cancel_running_job(self):
        import threading
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(2)
            return True

        job = JOBS.start("test", "cancel", slow)
        self.assertTrue(started.wait(2))
        out = JOBS.cancel(job["id"])
        self.assertEqual(out["state"], "canceling")
        release.set()
        done = wait(job["id"])
        self.assertEqual(done["state"], "canceled")

    def test_unknown_id(self):
        self.assertIsNone(JOBS.get("missing"))


if __name__ == "__main__":
    unittest.main()
