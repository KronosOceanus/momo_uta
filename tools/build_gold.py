#!/usr/bin/env python3
"""构建评测集：按规则分层抽取青空文庫的句子。

用法:
    python3 tools/build_gold.py --works 6 --scale 0.1     # 小样验证
    python3 tools/build_gold.py --works 40               # 正式构建

产物:
    eval/gold/gold.jsonl   每行 {id, source, work, author, text, spans, rules, primary}
    eval/plain.txt         没有 ruby 的句子（只用来算 coverage，不做 precision）
    eval/reports/manifest.json  配额 / 实际条数 / 种子 / 数据版本
    eval/coverage.md       分层覆盖表（给人看）

规则定义见 eval/rules.md，检测逻辑见 tools/rules.py。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aozora_parse import parse, check          # noqa: E402
from rules import label_line                   # noqa: E402

from common import GOLD, REPORTS, SOURCES

ROOT = Path(__file__).resolve().parent.parent
CACHE = SOURCES / "aozora"
INDEX = SOURCES / "index" / "list_person_all_extended_utf8.csv"

# 分层配额（rules.md）
# 分层配额。R2/R12 只作为「标签」记录，不单独设层：
# 它们几乎对每句都成立，设成层会把别的规则挤掉。
QUOTAS = {
    "R1": 260, "R3": 80, "R4": 60, "R5": 80, "R6": 60,
    "R7": 60, "R8": 40, "R9": 100, "R10": 60, "R11": 60,
}

UA = {"User-Agent": "NihongoTrans-eval/0.1 (research; contact: local)"}


def fetch(url: str, dst: Path, tries: int = 4) -> bool:
    """带重试的下载。缓存命中直接返回。"""
    if dst.exists() and dst.stat().st_size > 0:
        return True
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                dst.write_bytes(r.read())
            return True
        except Exception as e:
            wait = 2 ** i
            print(f"      ! 下载失败（{type(e).__name__}: {e}），{wait}s 后重试", flush=True)
            time.sleep(wait)
    return False


def decode(raw: bytes, enc: str) -> str:
    enc = (enc or "").lower()
    if "utf" in enc:
        return raw.decode("utf-8", errors="replace")
    for e in ("shift_jis", "cp932"):
        try:
            return raw.decode(e, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


SEP = re.compile(r"^-{20,}\s*$")


def extract_body_txt(txt: str) -> str:
    """青空文庫の ruby 付きテキスト：ヘッダの凡例と末尾の底本情報を落とす。"""
    lines = txt.split("\n")
    # ヘッダ末尾の区切り線（最初の 80 行以内で最後のもの）
    start = 0
    for i, ln in enumerate(lines[:80]):
        if SEP.match(ln.strip()):
            start = i + 1
    body = lines[start:]
    # フッタ（底本・入力・校正…）で切る
    out = []
    for ln in body:
        if re.match(r"^(底本|初出|入力|校正|青空文庫作成ファイル|このファイルは)", ln):
            break
        out.append(ln)
    return "\n".join(out)


def split_lines(body: str) -> list[str]:
    parts = re.split(r"<br\s*/?>|\r?\n", body)
    out = []
    for p in parts:
        t = re.sub(r"<[^>]+>", "", p).strip()
        t = t.replace("\u3000", " ")
        if t:
            out.append(t)
    return out


def load_index() -> list[dict]:
    rows = []
    with INDEX.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("文字遣い種別") != "新字新仮名":
                continue
            if r.get("作品著作権フラグ") != "なし":
                continue
            url = (r.get("テキストファイルURL") or "").strip()
            if not url.endswith(".zip") or "_ruby_" not in url:
                continue
            if any(w["work_id"] == r["作品ID"] for w in rows):
                continue
            rows.append({
                "work_id": r["作品ID"],
                "title": r["作品名"],
                "author": f'{r.get("姓","")}{r.get("名","")}'.strip(),
                "url": url,
                "enc": r.get("テキストファイル符号化方式", ""),
                "card": r.get("図書カードURL", ""),
            })
    return rows


def build(works: int, scale: float, seed: int) -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    quotas = {k: max(1, int(v * scale)) for k, v in QUOTAS.items()}
    rows = load_index()
    print(f"索引：{len(rows)} 部可用作品（新字新仮名・著作権なし）")

    rnd = random.Random(seed)
    rnd.shuffle(rows)
    picked = rows[:works]

    buckets: dict[str, list[dict]] = {k: [] for k in quotas}
    plain: list[str] = []
    seen: set[str] = set()
    used_works = 0

    for i, w in enumerate(picked, 1):
        dst = CACHE / f'{w["work_id"]}.zip'
        print(f"[{i}/{len(picked)}] {w['title']} / {w['author']}", flush=True)
        if not fetch(w["url"], dst):
            print("      × 跳过（下载失败）", flush=True)
            continue

        try:
            z = zipfile.ZipFile(io.BytesIO(dst.read_bytes()))
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            txt = decode(z.read(name), w["enc"])
        except Exception as e:
            print(f"      × 解压失败：{e}", flush=True)
            continue
        body = extract_body_txt(txt)
        lines = split_lines(body)
        got = 0
        for ln in lines:
            if len(ln) < 6 or len(ln) > 200:
                continue
            text, spans = parse(ln)
            if not spans:
                if len(plain) < 400:
                    plain.append(text)
                continue
            errs = check(text, spans)
            if errs:
                continue
            if text in seen:
                continue
            seen.add(text)

            lab = label_line(text, spans)
            # 公平分配：在「这句能填、且有剩余配额」的层里，挑缺口比例最大的那个
            cands = [r for r in lab["rules"] if r in buckets and len(buckets[r]) < quotas[r]]
            if not cands:
                # 没命中任何特殊规则 → 归入基线层 R1
                if len(buckets["R1"]) >= quotas["R1"]:
                    continue
                cands = ["R1"]
            prim = max(cands, key=lambda r: (quotas[r] - len(buckets[r])) / quotas[r])

            buckets[prim].append({
                "id": f'aozora-{w["work_id"]}-{len(buckets[prim]):04d}',
                "source": f'aozora/{w["work_id"]}',
                "work": w["title"],
                "author": w["author"],
                "card": w["card"],
                "text": text,
                "spans": spans,
                "rules": lab["rules"],
                "primary": prim,
            })
            got += 1
        used_works += 1
        print(f"      + {got} 句", flush=True)

    # 手工补充集（青空文庫里罕见的规则）
    manual = GOLD / "manual.jsonl"
    if manual.exists():
        for ln in manual.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            rec = json.loads(ln)
            prim = rec["primary"]
            if prim in buckets and len(buckets[prim]) < quotas[prim]:
                buckets[prim].append(rec)

    gold = [rec for k in quotas for rec in buckets[k]]
    with (GOLD / "gold.jsonl").open("w", encoding="utf-8") as f:
        for rec in gold:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (GOLD / "plain.txt").write_text("\n".join(plain), encoding="utf-8")

    manifest = {
        "seed": seed,
        "works_requested": works,
        "works_used": used_works,
        "quotas_target": quotas,
        "quotas_actual": {k: len(v) for k, v in buckets.items()},
        "gold_total": len(gold),
        "plain_total": len(plain),
        "index": str(INDEX.name),
    }
    (REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 分层覆盖表", "", "| 层 | 目标 | 实际 | 说明 |", "|---|---|---|---|"]
    for k, v in quotas.items():
        lines.append(f"| {k} | {v} | {len(buckets[k])} | |")
    lines.append(f"| **合计** | {sum(quotas.values())} | {len(gold)} | 另有 plain {len(plain)} 句 |")
    (REPORTS / "coverage_prose.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n=== 结果 ===")
    for k in quotas:
        flag = "✓" if len(buckets[k]) >= quotas[k] * 0.8 else "!"
        print(f"  {flag} {k}: {len(buckets[k])}/{quotas[k]}")
    print(f"  gold.jsonl = {len(gold)} 条，plain = {len(plain)} 句")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--works", type=int, default=40)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    build(a.works, a.scale, a.seed)


if __name__ == "__main__":
    main()
