#!/usr/bin/env python3
"""前端三文件的完整性检查：

1. 每个文件单独语法检查（node --check）
2. 三个文件按加载顺序拼起来再检查一次
   → 这一步能抓到"跨文件重复的顶层 let/const/function"，
     也就是历史上最容易犯的那类错（重复定义、漏声明）
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "nihonco_player" / "static"
ORDER = ["05-audio.js", "10-app.js", "20-editor.js", "30-playback.js"]


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


def main() -> int:
    ok = True
    for name in ORDER:
        p = STATIC / name
        if not p.is_file():
            print(f"✗ 缺少 {name}")
            ok = False
            continue
        ok &= node_check(p.read_text(encoding="utf-8"), name)
    joined = "\n".join((STATIC / n).read_text(encoding="utf-8") for n in ORDER
                       if (STATIC / n).is_file())
    ok &= node_check(joined, "三个文件合并后（检查跨文件重复定义）")
    if ok:
        print("前端检查通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
