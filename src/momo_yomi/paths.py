"""项目路径常量（引擎与工具共用，只有路径，没有逻辑）。

开发时所有目录都在仓库内；
打包后资源来自 .app，用户数据写到 Application Support。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_DEV_ROOT = Path(__file__).resolve().parents[2]
_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE = Path(getattr(sys, "_MEIPASS", _DEV_ROOT))
_OLD_HOME = Path.home() / "Library" / "Application Support" / "nihonco uta"
_NEW_HOME = Path.home() / "Library" / "Application Support" / "momo uta"
if _FROZEN and not _NEW_HOME.exists() and _OLD_HOME.is_dir():
    try:
        _OLD_HOME.rename(_NEW_HOME)     # 一次性迁移旧品牌数据
    except OSError:
        pass
ROOT = Path(os.environ.get("MOMO_HOME") or os.environ.get("NIHONCO_HOME") or (
    _NEW_HOME if _FROZEN else _DEV_ROOT
))
TOOLS = BUNDLE / "tools"
DATA = ROOT / "data"

# 数据按「能不能重建」分类
SOURCES = DATA / "sources"      # 原始下载（可整目录删）
TABLES = BUNDLE / "data" / "tables"   # 词典机械抽取（只读资源）
CURATED = DATA / "curated"      # 人工维护（不可重建，要备份）
CORPUS = (BUNDLE / "data" / "corpus") if _FROZEN else (DATA / "corpus")  # 运行时档位统计/开发语料
CACHE = DATA / "cache"          # 运行期缓存（随时可删）
LYRICS = DATA / "lyrics"        # 歌词标注（nhlrc，用户资产，进 git）
VOCALS = DATA / "vocals"        # 人声分离结果（可重算但很贵，单独存放）


# 评测
EVAL = ROOT / "eval"
GOLD = EVAL / "gold"            # 标准答案（资产）
REPORTS = EVAL / "reports"      # 自动生成（可重建）

# 配置
CONFIG = BUNDLE / "config"


def bootstrap() -> None:
    """打包后首次启动：建用户目录，补一份默认排除词。"""
    if not _FROZEN:
        return
    import shutil
    for d in (CURATED, CACHE, LYRICS, VOCALS, ROOT / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    for name in ("lyrics_exclude.json", "glossary_lyrics.json", "counters.json"):
        seed = BUNDLE / "data" / "curated" / name
        target = CURATED / name
        if seed.is_file() and not target.exists():
            shutil.copy2(seed, target)


if _FROZEN:
    bootstrap()
