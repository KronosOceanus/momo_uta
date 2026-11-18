#!/usr/bin/env python3
"""桌面应用：在随机端口起服务，用系统 webview 开窗口。这是唯一入口。

开发时也可 `python -m nihonco_player_app`；正式使用 `make app`。
"""
from __future__ import annotations

import threading

import webview
from webview import FileDialog

from nihonco_player import library as LIB
from nihonco_player import server as SRV


def main() -> None:
    lib = LIB.scan_library()
    SRV.CACHE.update({str(i): x for i, x in enumerate(lib)})

    srv = SRV.make_server(0)                     # 随机端口，不占 8766
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    class Api:
        """前端只调 pick_any()：一个对话框里文件、文件夹都能选，程序自己判断。"""

        def pick_any(self):
            """一个对话框，文件和文件夹都能选（NSOpenPanel 两个开关都打开）。"""
            try:
                from AppKit import NSOpenPanel
                from PyObjCTools import AppHelper

                out: dict = {}
                done = threading.Event()

                def show():                    # NSOpenPanel 必须在主线程
                    try:
                        panel = NSOpenPanel.openPanel()
                        panel.setCanChooseFiles_(True)
                        panel.setCanChooseDirectories_(True)
                        panel.setAllowsMultipleSelection_(True)
                        panel.setPrompt_("导入")
                        panel.setMessage_("文件夹、音频或歌词都可以选")
                        out["paths"] = [u.path() for u in panel.URLs()] if panel.runModal() else []
                    except Exception:
                        out["paths"] = []
                    finally:
                        done.set()

                AppHelper.callAfter(show)
                done.wait(300)
                return out.get("paths", [])
            except Exception:
                r = webview.windows[0].create_file_dialog(FileDialog.FOLDER)
                return list(r) if r else []

        """兼容旧接口"""
        def pick_folder(self):
            r = webview.windows[0].create_file_dialog(FileDialog.FOLDER)
            return r[0] if r else ""

        def pick_files(self):
            return webview.windows[0].create_file_dialog(
                FileDialog.OPEN, allow_multiple=True,
                file_types=("音频 (*.mp3;*.flac;*.wav;*.m4a)", "歌词 (*.lrc)"))

    webview.create_window(
        "にほんご歌练习", f"http://127.0.0.1:{port}/",
        width=1280, height=820, min_size=(960, 600), js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    main()
