#!/usr/bin/env python3
"""启动 seek-bench 静态页。"""
from __future__ import annotations

import http.server
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
print("http://127.0.0.1:8766/bench.html")
http.server.ThreadingHTTPServer(("127.0.0.1", 8766), http.server.SimpleHTTPRequestHandler).serve_forever()
