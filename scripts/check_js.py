#!/usr/bin/env python3
"""前端脚本的完整性检查：

1. 每个文件单独语法检查（node --check）
2. 五个文件按加载顺序拼起来再检查一次（抓跨文件重复定义/漏声明）
3. 命名空间检查：每个脚本必须是 IIFE，且只通过 window.NH 暴露东西
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "momo_player" / "static"
ORDER = ["05-audio.js", "06-state.js", "10-app.js", "11-vocals.js", "12-library.js", "20-editor.js", "30-playback.js", "40-shortcuts.js"]


def node_check(code: str, label: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(code)
        tmp = fh.name
    r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    Path(tmp).unlink()
    if r.returncode:
        print(f"✗ {label}\n{r.stderr.strip()}")
        return False
    return True


def check_namespace(name: str, src: str) -> bool:
    """每个脚本都要是 (function(){ ... })(); 且通过 window.NH 导出。"""
    body = src.lstrip()
    if "(function(){" not in body[:200]:
        print(f"✗ {name}: 没有包成 IIFE（顶层会漏成全局）")
        return False
    if "const NH = window.NH" not in src:
        print(f"✗ {name}: 没有取 window.NH")
        return False
    return True


def main() -> int:
    ok = True
    for name in ORDER:
        p = STATIC / name
        if not p.is_file():
            print(f"✗ 缺少 {name}")
            ok = False
            continue
        src = p.read_text(encoding="utf-8")
        ok &= check_namespace(name, src)
        ok &= node_check(src, name)
    joined = "\n".join((STATIC / n).read_text(encoding="utf-8") for n in ORDER
                       if (STATIC / n).is_file())
    ok &= node_check(joined, "三个文件合并后（检查跨文件重复定义）")
    if ok:
        print("前端检查通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
