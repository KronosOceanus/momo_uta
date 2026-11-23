"""兼容层：评测脚本仍 `from common import …`，实际实现在 momo_yomi.common。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from momo_yomi.common import *  # noqa: F401,F403,E402
