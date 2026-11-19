#!/usr/bin/env python3
"""HTTP 启动：起线程服务（app 壳调用）。"""
from __future__ import annotations

from http.server import ThreadingHTTPServer

from ..core import library as LIB
from ..core.library import CACHE
from .routes import H


def make_server(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), H)


def main() -> None:
    n = LIB.refresh()
    srv = make_server(8766)
    print(f"{n} 首有歌词 → http://127.0.0.1:{srv.server_address[1]}")
    srv.serve_forever()
