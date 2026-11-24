#!/usr/bin/env python3
"""桌面应用：在随机端口起服务，用系统 webview 开窗口。这是唯一入口。

开发时也可 `python -m momo_uta_app`；正式使用 `make app`。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import webview
from webview import FileDialog
from webview.menu import Menu, MenuAction

from momo_yomi.config import APP
from momo_yomi.paths import BUNDLE, bootstrap

from momo_player.core import library as LIB
from momo_player.core import vocals as VOC
from momo_player.http.server import make_server
from momo_player.core import jobs as JOBS

from momo_uta_app import logsetup


def _bundle_path() -> None:
    """让 full 包里的 ffmpeg 优先于系统 PATH。"""
    import os
    b = BUNDLE / "bin"
    if b.is_dir():
        os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def _run_demucs() -> None:
    """full 包内 demucs 子进程入口，不启动窗口。"""
    import importlib
    demucs_main = importlib.import_module("demucs.separate").main
    sys.argv = ["demucs", *sys.argv[2:]]
    demucs_main()


def _show_startup_error(exc: Exception) -> None:
    """启动失败时给用户一个可见出口；日志仍保留完整 traceback。"""
    import traceback
    print(traceback.format_exc(), file=sys.stderr)
    detail = f"{type(exc).__name__}: {exc}"
    try:
        from AppKit import NSAlert, NSApplication
        from momo_yomi.paths import CACHE
        alert = NSAlert.alloc().init()
        alert.setMessageText_("桃歌启动失败")
        alert.setInformativeText_(detail[:1200] + "\n\n日志：" + str(CACHE / "app.log"))
        alert.addButtonWithTitle_("退出")
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert.runModal()
    except Exception:
        pass


def _acquire_instance_lock(path: str | Path | None = None):
    """拿 data/app.lock 的非阻塞排他锁；失败说明已有实例。"""
    try:
        import fcntl
    except ImportError:                       # pragma: no cover - macOS target
        return None
    from momo_yomi.paths import ROOT
    p = Path(path) if path is not None else ROOT / "data" / "app.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _already_running() -> None:
    """短暂提示后自动消失，不要求用户点确认。"""
    try:
        from AppKit import NSAlert, NSApplication, NSModalPanelRunLoopMode
        from Foundation import NSRunLoop, NSTimer
        app = NSApplication.sharedApplication()
        alert = NSAlert.alloc().init()
        alert.setMessageText_("桃歌已经在运行")
        alert.setInformativeText_("请切换到已打开的窗口。")
        alert.addButtonWithTitle_("好")
        timer = NSTimer.timerWithTimeInterval_repeats_block_(
            1.5, False, lambda _t: app.abortModal())
        NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSModalPanelRunLoopMode)
        app.activateIgnoringOtherApps_(True)
        alert.runModal()
    except Exception:
        print("桃歌已经在运行", file=sys.stderr)


def _run_app(demo: bool = False, demo_auto: bool = False,
             demo_script: str = "demo_driver.js") -> None:
    from momo_player.core import diag
    # 先抢单实例锁，避免第二个实例写日志/轮转第一个实例的日志。
    instance_lock = _acquire_instance_lock()
    if instance_lock is None:
        _already_running()
        return
    try:
        log_path = logsetup.setup()
    except Exception as e:
        log_path = None
        print(f"日志初始化失败：{e}", file=sys.stderr)
    sys.excepthook = logsetup.log_exception
    if log_path:
        print(f"日志：{log_path}")
    diag.log("app", f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable} bundle={BUNDLE}")
    _bundle_path()
    bootstrap()
    LIB.load_cache_for_playlists()
    VOC.cleanup(protected={v.get("uid") for v in LIB.CACHE.values()})

    srv = make_server(0)                     # 随机端口，不占 8766
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    shutdown_done = threading.Event()
    shutdown_ok = {"value": False}

    class Api:
        """前端只调 pick_any()：一个对话框里文件、文件夹都能选，程序自己判断。"""

        def shutdown_ready(self, ok=True):
            shutdown_ok["value"] = bool(ok)
            shutdown_done.set()
            return {"ok": True}


        def open_data_dir(self):
            """用 Finder 打开当前用户数据目录；路径由后端决定，前端不硬编码。"""
            try:
                import subprocess
                from momo_yomi.paths import DATA
                DATA.mkdir(parents=True, exist_ok=True)
                subprocess.run(["open", str(DATA)], check=False)
                return {"ok": True, "path": str(DATA)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

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

        def save_text(self, default_name: str, text: str, alt_text: str = ""):
            """保存文本；.lrc 扩展名写 alt_text（纯 LRC），其余写 text（.nhlrc）。"""
            try:
                r = webview.windows[0].create_file_dialog(
                    FileDialog.SAVE, save_filename=default_name)
                if not r:
                    return ""
                path = r if isinstance(r, str) else r[0]
                body = alt_text if (alt_text and path.lower().endswith(".lrc")) else text
                Path(path).write_text(body, encoding="utf-8")
                return path
            except Exception:
                return ""

        def pick_lrc_text(self):
            """选一个 .lrc / .nhlrc，返回 {"name","text"}；取消返回空。"""
            try:
                r = webview.windows[0].create_file_dialog(
                    FileDialog.OPEN, allow_multiple=False,
                    file_types=("歌词 (*.lrc;*.nhlrc)", "全部文件 (*.*)"))
                if not r:
                    return {}
                path = r if isinstance(r, str) else r[0]
                return {"name": Path(path).name,
                        "text": Path(path).read_text(encoding="utf-8", errors="ignore")}
            except Exception:
                return {}

        def pick_files(self):
            return webview.windows[0].create_file_dialog(
                FileDialog.OPEN, allow_multiple=True,
                file_types=("音频 (*.mp3;*.flac;*.wav;*.m4a)", "歌词 (*.lrc)"))

    window_ref: dict = {"window": None}

    def show_window():
        try:
            w = window_ref.get("window")
            if w:
                w.show()
        except Exception:
            pass

    # 关闭窗口只隐藏，音频和全局热键继续；⌘Q 仍正常退出。
    if sys.platform == "darwin":
        try:
            from webview.platforms import cocoa

            class HideOnClose(cocoa.BrowserView.WindowDelegate):
                def windowShouldClose_(self, window):
                    i = cocoa.BrowserView.get_instance("window", window)
                    if i:
                        w = i.pywebview_window
                        # 隐藏窗口后仍让前端把当前 LRC 草稿落盘；不阻塞关闭。
                        def flush():
                            try:
                                w.evaluate_js(
                                    "NH.prepareBackgroundFlush && NH.prepareBackgroundFlush()")
                            except Exception:
                                pass
                        threading.Thread(target=flush, daemon=True,
                                         name="hide-flush").start()
                        w.hide()
                    return False

            class ReopenOnDock(cocoa.BrowserView.AppDelegate):
                def applicationShouldHandleReopen_hasVisibleWindows_(self, app, has_visible):
                    show_window()
                    return True

            cocoa.BrowserView.WindowDelegate = HideOnClose
            cocoa.BrowserView.AppDelegate = ReopenOnDock
        except Exception:
            pass

    window = webview.create_window(
        "桃歌", f"http://127.0.0.1:{port}/",
        width=APP["window_width"], height=APP["window_height"],
        min_size=tuple(APP["window_min"]), js_api=Api(),
    )
    window_ref["window"] = window
    if demo:
        from momo_uta_app import demo as DEMO
        DEMO.install(window, auto=demo_auto, script_name=demo_script)

    def on_hotkey(name):
        js = {"prev": "NH.mediaPrev && NH.mediaPrev()",
              "next": "NH.mediaNext && NH.mediaNext()",
              "toggle": "NH.mediaToggle && NH.mediaToggle()"}.get(name)
        if not js:
            return
        # Carbon 回调在主线程；evaluate_js 会等待主线程执行，
        # 直接调用会死锁。切到后台线程，让主线程继续跑 WebView。
        def run():
            try:
                window.evaluate_js(js)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    try:
        from momo_uta_app import hotkeys as GLOBAL_KEYS
        GLOBAL_KEYS.install(on_hotkey)
    except Exception:
        pass

    allow_quit = {"value": False}
    quitting = {"value": False}

    def on_closing():
        """Cmd+Q 时先让前端保存；窗口关闭按钮已经在 Cocoa 层改为隐藏。"""
        if allow_quit["value"]:
            return True
        if quitting["value"]:
            return False
        quitting["value"] = True
        shutdown_done.clear()
        shutdown_ok["value"] = False

        def run():
            try:
                window.evaluate_js("NH.prepareShutdown && NH.prepareShutdown()")
            except Exception:
                pass
            if not shutdown_done.wait(5):
                quitting["value"] = False
                try:
                    window.evaluate_js("NH.done && NH.done('保存超时，已取消退出')")
                except Exception:
                    pass
                return
            if not shutdown_ok["value"]:
                quitting["value"] = False
                return
            allow_quit["value"] = True
            try:
                from AppKit import NSApplication
                from PyObjCTools import AppHelper
                AppHelper.callAfter(lambda: NSApplication.sharedApplication().terminate_(None))
            except Exception:
                try:
                    window.destroy()
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True, name="quit-save").start()
        return False

    window.events.closing += on_closing

    try:
        webview.start(menu=[Menu("窗口", [MenuAction("显示窗口", show_window)])])
    finally:
        try:
            JOBS.cancel_all()
        except Exception:
            pass
        try:
            VOC.cancel_all()
        except Exception:
            pass
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
        try:
            instance_lock.close()
        except Exception:
            pass


def main(demo: bool = False, demo_auto: bool = False,
         demo_script: str = "demo_driver.js") -> None:
    try:
        _run_app(demo=demo, demo_auto=demo_auto, demo_script=demo_script)
    except Exception as e:
        _show_startup_error(e)
        raise


if __name__ == "__main__":
    # PyInstaller + torch/demucs: 子进程会重新执行本可执行文件。
    # 不先 freeze_support，它们会进入 main()，再开一个窗口。
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--momo-demucs":
        _run_demucs()
    else:
        demo2 = "--demo2" in sys.argv or "--demo2-auto" in sys.argv
        main(demo=("--demo" in sys.argv or "--demo-auto" in sys.argv or demo2),
             demo_auto=("--demo-auto" in sys.argv or "--demo2-auto" in sys.argv),
             demo_script=("demo2_driver.js" if demo2 else "demo_driver.js"))
