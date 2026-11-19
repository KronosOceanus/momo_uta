"""项目路径常量（引擎与工具共用，只有路径，没有逻辑）。

只有路径常数：改目录结构只动这一个文件。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
DATA = ROOT / "data"

# 数据按「能不能重建」分类
SOURCES = DATA / "sources"      # 原始下载（可整目录删）
TABLES = DATA / "tables"        # 词典机械抽取（可重建）
CURATED = DATA / "curated"      # 人工维护（不可重建，要备份）
CORPUS = DATA / "corpus"        # 语料统计（可重建）
CACHE = DATA / "cache"          # 运行期缓存（随时可删）


# 评测
EVAL = ROOT / "eval"
GOLD = EVAL / "gold"            # 标准答案（资产）
REPORTS = EVAL / "reports"      # 自动生成（可重建）

# 演示
DEMO_SRC = ROOT / "demo" / "src"
DEMO_OUT = ROOT / "demo" / "out"

# 配置
CONFIG = ROOT / "config"
