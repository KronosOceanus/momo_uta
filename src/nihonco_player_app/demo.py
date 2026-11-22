"""--demo：页面内演示驱动，不改变正常启动路径。"""
from __future__ import annotations

import threading
import time
from pathlib import Path


def install(window, auto: bool = False) -> None:
    script = Path(__file__).with_name("demo_driver.js").read_text(encoding="utf-8")

    def boot():
        # 等静态页面和 NH 脚本就绪；最多等 20 秒。
        for _ in range(100):
            try:
                if window.evaluate_js("!!(window.NH && NH.LIB && NH.LIB.length)"):
                    window.evaluate_js(script)
                    if auto:
                        time.sleep(0.3)
                        window.evaluate_js("window.__nihoncoDemoPrepare && window.__nihoncoDemoPrepare()")
                        time.sleep(12)
                        window.evaluate_js("window.__nihoncoDemoStart && window.__nihoncoDemoStart()")
                    return
            except Exception:
                pass
            time.sleep(0.2)

    threading.Thread(target=boot, daemon=True).start()
