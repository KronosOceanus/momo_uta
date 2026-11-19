#!/usr/bin/env python3
"""兼容入口：实际的 HTTP 实现在 http/，业务在 service/，数据在 core/。

外部（app 壳、测试）继续 from nihonco_player import server 即可。
"""
from __future__ import annotations

from .core import edits as ED  # noqa: F401
from .core import library as LIB  # noqa: F401
from .core import lrcio as LRC  # noqa: F401
from .core import lyrics as LY  # noqa: F401
from .core import playlists as PL  # noqa: F401
from .core.library import CACHE  # noqa: F401
from .http.routes import H  # noqa: F401
from .http.server import main, make_server  # noqa: F401
from .service.song import song_payload  # noqa: F401
