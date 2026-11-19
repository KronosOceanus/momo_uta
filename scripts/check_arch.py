#!/usr/bin/env python3
"""架构边界检查：违反依赖规则就退出码 1。

规则（见 docs/architecture.md §2）：
  1. nihonco_yomi 不能 import 任何 nihonco_player*
  2. core 不能 import service / http
  3. service 不能 import http
  4. http 不能 import nihonco_player_app
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RULES = {
    "src/nihonco_yomi": ("nihonco_player", "nihonco_player_app"),
    "src/nihonco_player/core": ("nihonco_player.service", "nihonco_player.http",
                                "nihonco_player_app"),
    "src/nihonco_player/service": ("nihonco_player.http", "nihonco_player_app"),
    "src/nihonco_player/http": ("nihonco_player_app",),
}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = module_name(path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # 相对导入 → 绝对
                base = pkg.split(".")
                base = base[: len(base) - node.level] if node.level <= len(base) else []
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append(mod)
    return [m for m in out if m]


def main() -> int:
    bad = []
    for pkg_dir, forbidden in RULES.items():
        d = ROOT / pkg_dir
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            here = module_name(f)
            for mod in imports_of(f):
                if here == mod or mod.startswith(here + "."):
                    continue
                for f_ in forbidden:
                    if mod == f_ or mod.startswith(f_ + "."):
                        bad.append(f"{f.relative_to(ROOT)}: import {mod}（禁止：{f_}）")
    if bad:
        print("架构越界：")
        for b in bad:
            print("  " + b)
        return 1
    print("架构检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
