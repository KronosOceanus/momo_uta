#!/usr/bin/env python3
"""前端脚本的完整性检查：

1. 每个文件单独语法检查（node --check）
2. 所有文件按加载顺序拼起来再检查一次（合并后的语法）
3. 命名空间检查：每个脚本必须是 IIFE，且只通过 window.NH 暴露东西
4. 跨文件重复导出检查：Object.assign(NH, {...}) 的键不能重复
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "momo_player" / "static"
DEMO = ROOT / "src" / "momo_uta_app"
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


EXPORT_RE = re.compile(r"Object\.assign\(NH,\s*\{(.*?)\}\)", re.S)
EXPORT_NAME_RE = re.compile(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*(?=,|$)")


def check_exports() -> bool:
    seen: dict[str, str] = {}
    ok = True
    for name in ORDER:
        p = STATIC / name
        if not p.is_file():
            continue
        for body in EXPORT_RE.findall(p.read_text(encoding="utf-8")):
            for key in EXPORT_NAME_RE.findall(body):
                if key in seen:
                    print(f"✗ 重复导出 NH.{key}: {seen[key]} / {name}")
                    ok = False
                else:
                    seen[key] = name
    return ok


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
    ok &= node_check(joined, "所有文件合并后（语法）")
    ok &= check_exports()
    for name in ("demo_driver.js",):
        p = DEMO / name
        if not p.is_file():
            print(f"✗ 缺少 {name}")
            ok = False
        else:
            ok &= node_check(p.read_text(encoding="utf-8"), name)
    if ok:
        print("前端检查通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
