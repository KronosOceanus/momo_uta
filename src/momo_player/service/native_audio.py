"""原生音频 helper 的最小 Python 桥。

Swift helper 通过 stdin/stdout JSON 通信；音频解码和输出不经过 WKWebView。
"""
from __future__ import annotations

import atexit
import json
import select
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..core import library as LIB
from . import soundtouch as ST

_LOCK = threading.RLock()
_PROC: subprocess.Popen | None = None
_SEQ = 0
_TIMEOUT = 2.0


def _helper_path() -> Path | None:
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent.parent / "Helpers" / "momo-audio"
        if p.is_file():
            return p
    root = Path(__file__).resolve().parents[3]
    p = root / "dist" / "native" / "momo-audio"
    return p if p.is_file() else None


def _start() -> subprocess.Popen:
    global _PROC
    if _PROC and _PROC.poll() is None:
        return _PROC
    helper = _helper_path()
    if not helper:
        raise RuntimeError("原生音频 helper 未构建")
    _PROC = subprocess.Popen(
        [str(helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1, close_fds=True)
    return _PROC


def _stop() -> None:
    global _PROC
    p, _PROC = _PROC, None
    if not p:
        return
    try:
        if p.stdin:
            p.stdin.write('{"cmd":"quit"}\n')
            p.stdin.flush()
    except (OSError, ValueError):
        pass
    try:
        p.wait(timeout=1)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            p.kill()


atexit.register(_stop)


def _cmd(payload: dict) -> dict:
    global _SEQ
    with _LOCK:
        p = _start()
        if not p.stdin or not p.stdout:
            raise RuntimeError("原生音频 helper 管道不可用")
        _SEQ += 1
        req = dict(payload)
        req["id"] = _SEQ
        p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        p.stdin.flush()
        ready, _, _ = select.select([p.stdout], [], [], _TIMEOUT)
        if not ready:
            _stop()
            raise RuntimeError("原生音频 helper 超时")
        line = p.stdout.readline()
        if not line:
            _stop()
            raise RuntimeError("原生音频 helper 已退出")
        try:
            out = json.loads(line)
        except json.JSONDecodeError as e:
            _stop()
            raise RuntimeError("原生音频 helper 返回非法 JSON") from e
        if not out.get("ok"):
            raise RuntimeError(out.get("error") or "原生音频操作失败")
        return out


def _resolve(src: str) -> str:
    """只接受 /audio/<uid> 或库内路径；不把任意路径暴露给前端。"""
    src = str(src or "")
    if src.startswith("/audio/"):
        u = urlsplit(src)
        uid = unquote(u.path[len("/audio/"):])
        item = LIB.resolve(uid)
        if not item:
            raise KeyError("歌曲已不可用")
        q = parse_qs(u.query)
        if q.get("st"):
            path = ST.cached_path(uid, float(q["st"][0]),
                                  int((q.get("key") or ["0"])[0]))
            if not path:
                raise KeyError("变速缓存不存在")
            return str(path)
        return str(item["file"])
    p = Path(src)
    if not p.is_file():
        raise KeyError("音频文件不存在")
    return str(p)


def action(req: dict) -> dict:
    act = str(req.get("action") or "status")
    if act == "load":
        out = _cmd({"cmd": "load", "path": _resolve(req.get("src"))})
    elif act == "play":
        out = _cmd({"cmd": "play"})
    elif act == "pause":
        out = _cmd({"cmd": "pause"})
    elif act == "seek":
        out = _cmd({"cmd": "seek", "seconds": float(req.get("seconds") or 0)})
    elif act == "volume":
        out = _cmd({"cmd": "volume", "value": float(req.get("value") or 0)})
    elif act == "status":
        out = _cmd({"cmd": "status"})
    elif act == "stop":
        out = _cmd({"cmd": "stop"})
    else:
        return {"ok": False, "error": "未知原生音频动作"}
    return {"ok": True, **out}


def status() -> dict:
    return action({"action": "status"})


def close() -> None:
    _stop()
