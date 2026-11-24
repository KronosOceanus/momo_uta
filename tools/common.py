"""兼容层：评测脚本仍 `from common import …`，实际实现在 momo_yomi.common。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from momo_yomi.common import (  # noqa: E402
    Annotator, DEFAULT_CMD, EVAL, GOLD, REPORTS, ROOT,
    load_gold, normalize, run_all, segments_of,
)
from momo_yomi.paths import (  # noqa: E402
    CACHE, CORPUS, CURATED, DATA, SOURCES, TABLES, TOOLS,
)

__all__ = [
    "CACHE", "CORPUS", "CURATED", "DATA", "ROOT", "EVAL",
    "GOLD", "REPORTS", "SOURCES", "TABLES", "TOOLS",
    "DEFAULT_CMD", "Annotator",
    "segments_of", "run_all", "load_gold", "normalize",
]
