"""前端冒烟测试：真开一个 pywebview 窗口，验证页面能渲染、点歌能出歌词。

需要图形环境（macOS 桌面）。没有 GUI 或没装 pywebview 时自动跳过。
"""
import sys
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import webview
    HAVE_WEBVIEW = True
except Exception:                     # pragma: no cover
    HAVE_WEBVIEW = False

from momo_player.core import library as LIB
from momo_player.core import lrc_files as LRF
from momo_player.core import vocals as VOC
from momo_player.core.library import CACHE
from momo_player.http.server import make_server
from momo_player.http.routes import TOKEN


@unittest.skipUnless(HAVE_WEBVIEW, "没有 pywebview")
class TestUiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._lyr_tmp = tempfile.TemporaryDirectory()
        cls._lyr_patch = patch.object(LRF, "LYRICS", Path(cls._lyr_tmp.name) / "lyrics")
        cls._lyr_patch.start()
        cls._voc_patch = patch.object(VOC, "VOCALS", Path(cls._lyr_tmp.name) / "vocals")
        cls._voc_patch.start()
        lib = LIB.scan_library()
        LIB._publish(lib)
        if not lib:
            raise unittest.SkipTest("库里没有歌，跳过界面测试")
        cls.uid = next((v.get("uid") for v in CACHE.values() if v.get("has_lyric")), None)
        if cls.uid is None:
            raise unittest.SkipTest("库里没有带歌词的歌")
        cls.srv = make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:
            pass
        cls._lyr_patch.stop()
        cls._voc_patch.stop()
        cls._lyr_tmp.cleanup()

    def _run_window(self, actions):
        """开窗口 → 等页面就绪 → 依次执行 actions(window) → 关闭。"""
        out = {}

        def worker(window):
            time.sleep(5)                 # 等 fetch + 渲染
            window.evaluate_js("window.__err=[];"
                               "addEventListener('error',e=>__err.push(e.message));"
                               "addEventListener('unhandledrejection',e=>__err.push('rej:'+e.reason))")
            for fn in actions:
                fn(window)
            out["err"] = window.evaluate_js("(__err||[]).join(' | ')")

        window = webview.create_window(
            "ui-smoke", f"http://127.0.0.1:{self.port}/#token={TOKEN}", width=1000, height=700)

        def safe_worker(w):
            try:
                worker(w)
            except Exception as e:            # 任何异常都要关窗，不能让测试挂住
                out["fatal"] = str(e)
            finally:
                try:
                    w.destroy()
                except Exception:
                    pass

        threading.Thread(target=safe_worker, args=(window,), daemon=True).start()
        threading.Timer(40, lambda: window.destroy()).start()   # 兜底：最多 40 秒
        webview.start()
        return out

    def test_playlists_render_and_song_opens(self):
        results = {}

        def check_playlists(w):
            results["pl"] = w.evaluate_js("document.querySelectorAll('.pl').length")
            results["it"] = w.evaluate_js("document.querySelectorAll('.it').length")

        def click_song(w):
            w.evaluate_js(f"NH.load('{self.uid}')")
            time.sleep(3)
            results["lines"] = w.evaluate_js("document.querySelectorAll('#lyr .ln').length")
            results["side"] = w.evaluate_js("document.querySelectorAll('#rmcol .ln2').length")

        out = self._run_window([check_playlists, click_song])
        self.assertGreater(results.get("pl", 0), 0, "歌单没渲染出来")
        self.assertGreaterEqual(results.get("it", 0), 0)
        self.assertGreater(results.get("lines", 0), 0, "点歌后没有歌词行")
        self.assertGreater(results.get("side", 0), 0, "右侧罗马音没出来")
        self.assertNotIn("fatal", out, f"测试线程异常：{out.get('fatal')}")
        self.assertEqual(out.get("err", ""), "", f"页面有 JS 错误：{out.get('err')}")


if __name__ == "__main__":
    unittest.main()
