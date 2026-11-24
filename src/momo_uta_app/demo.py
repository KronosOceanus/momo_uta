"""源码演示模式：按步骤驱动现有页面，不参与正常启动。"""
from __future__ import annotations

import threading
import time
from pathlib import Path


def install(window, auto: bool = False, script_name: str = "demo_driver.js") -> None:
    script = Path(__file__).with_name(script_name).read_text(encoding="utf-8")

    def boot():
        for _ in range(120):
            try:
                if window.evaluate_js("!!(window.NH && NH.LIB && NH.LIB.length)"):
                    window.evaluate_js(script)
                    if auto:
                        time.sleep(0.3)
                        window.evaluate_js("window.__demoStart && window.__demoStart()")
                    return
            except Exception:
                pass
            time.sleep(0.2)

    threading.Thread(target=boot, daemon=True).start()
