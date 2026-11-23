#!/usr/bin/env python3
"""Uta-Net 语料工厂：三个模式共用同一套抓取与解析。

    python tools/fetch_jpop.py               # 开发集 → eval/gold/lyrics.jsonl
    python tools/fetch_jpop.py --holdout     # 留出集 → eval/gold/lyrics_test.jsonl
    python tools/fetch_jpop.py --resource    # 词→读音 → data/corpus/utaten_resource.json

三个模式的纪律相同：**按 URL 排除评测集已用过的歌，保证零泄漏**。

原始需求：从 Uta-Net 动漫榜抓歌词，构建「J-Pop / 动漫歌」评测集。

入口是榜单页（不需要搜索接口）：https://utaten.com/ranking/anime/
歌词页自带人工振假名：<span class="ruby"><span class="rb">素直</span><span class="rt">すなお</span></span>
同页还有 <div class="romaji">，可存官方罗马音用于校验转写层。

用法:
    python3 tools/fetch_jpop.py --top 30 --cap 80
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.eval.rules import label_line                     # noqa: E402
from momo_yomi.kana import kata_to_hira

from tools.common import CORPUS, GOLD, REPORTS, SOURCES

ROOT = Path(__file__).resolve().parents[2]
CACHE = SOURCES / "lyrics"
RANKING = "https://utaten.com/ranking/anime/"

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "ja,en;q=0.8",
}

RUBY = re.compile(
    r'<span class="ruby">\s*<span class="rb">(.*?)</span>\s*<span class="rt">(.*?)</span>\s*</span>',
    re.S,
)


def get(url: str, tries: int = 3, timeout: int = 30) -> str:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in ("utf-8", "cp932"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")



def ranking_links(limit: int) -> list[str]:
    html = get(RANKING)
    links: list[str] = []
    for m in re.finditer(r'href="(/lyric/[a-z]{2}\d+/)"', html):
        if m.group(1) not in links:
            links.append(m.group(1))
        if len(links) >= limit:
            break
    return ["https://utaten.com" + x for x in links]


TIEIN = re.compile(r"\s+(TVアニメ|アニメ|映画|劇場版|ドラマ|CM|ゲーム|OVA|「)")


def clean_artist(a: str) -> str:
    return re.split(TIEIN, a)[0].strip()


def meta_of(html: str, fallback: str) -> tuple[str, str]:
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    head = m.group(1).strip() if m else ""
    mm = re.match(r"^(.*?)\s*歌詞\s*(.*?)\s*ふりがな付", head)
    if mm:
        return mm.group(1).strip(), clean_artist(mm.group(2))
    mm = re.match(r"^(.*?)\s*歌詞\s*(.*)", head)
    if mm:
        return mm.group(1).strip(), clean_artist(mm.group(2))
    return fallback, ""


def parse_page(html: str) -> list[tuple[str, str]]:
    i = html.find('class="hiragana"')
    if i < 0:
        return []
    j = html.find('<div class="romaji"', i)
    body = html[i:j if j > 0 else i + 30000]

    def to_lines(s: str, keep: str) -> list[str]:
        if keep == "rb":
            s = RUBY.sub(lambda m: f"｜{m.group(1)}《{kata_to_hira(m.group(2))}》", s)
        else:
            s = RUBY.sub(lambda m: m.group(2), s)
        s = re.sub(r"<br\s*/?>", "\n", s)
        s = re.sub(r"<[^>]+>", "", s)
        return [re.sub(r"\s+", " ", ln).strip() for ln in s.split("\n")]

    lines = to_lines(body, "rb")
    romaji: list[str] = []
    if j > 0:
        k = html.find("</span></div>", j)
        k = k if k > 0 else html.find("</div>", j)
        romaji = to_lines(html[j:k], "rt")
    if len(romaji) < len(lines):
        romaji += [""] * (len(lines) - len(romaji))
    return list(zip(lines, romaji))


def to_spans(text: str) -> tuple[str, list[dict]]:
    out: list[str] = []
    spans: list[dict] = []
    i, n = 0, len(text)
    pending = None
    while i < n:
        ch = text[i]
        if ch == "｜":
            pending = len(out)
            i += 1
            continue
        if ch == "《":
            close = text.find("》", i + 1)
            if close < 0:
                out.append(ch)
                i += 1
                continue
            start = pending if pending is not None else len(out)
            base = "".join(out[start:])
            ruby = text[i + 1:close]
            if base and ruby:
                spans.append({"start": start, "end": len(out), "base": base, "ruby": ruby})
            pending = None
            i = close + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), spans


def build_gold(top: int, cap: int) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--cap", type=int, default=80)
    a = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    urls = ranking_links(a.top)
    print(f"动漫榜：取前 {len(urls)} 首")

    records, matrix = [], {}
    for idx, url in enumerate(urls, 1):
        slug = url.rstrip("/").split("/")[-1]
        cache = CACHE / f"{slug}.html"
        try:
            if cache.exists():
                html = cache.read_text(encoding="utf-8")
            else:
                html = get(url)
                cache.write_text(html, encoding="utf-8")
                time.sleep(0.8)
        except Exception as e:
            print(f"[{idx}] × {slug} 抓取失败：{e}")
            continue

        title, artist = meta_of(html, slug)
        pairs = parse_page(html)
        used, work_rules = 0, {}
        for ln, ro in pairs:
            if used >= a.cap:
                break
            if len(ln) < 3 or len(ln) > 80:
                continue
            text, spans = to_spans(ln)
            if not spans:
                continue
            if any(text[s["start"]:s["end"]] != s["base"] for s in spans):
                continue
            lab = label_line(text, spans)
            for r in lab["rules"]:
                work_rules[r] = work_rules.get(r, 0) + 1
            records.append({
                "id": f"jpop-{slug}-{used:03d}",
                "source": "utaten",
                "domain": "lyrics",
                "title": title,
                "artist": artist,
                "url": url,
                "text": text,
                "spans": spans,
                "romaji_official": ro,
                "rules": lab["rules"],
                "primary": lab["primary"],
            })
            used += 1
        if used:
            matrix[f"{title} / {artist}"] = work_rules
            print(f"[{idx}/{len(urls)}] {title} / {artist}  +{used} 行")

    with (GOLD / "lyrics.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    all_rules = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]
    lines = ["# 歌词域覆盖矩阵（动漫歌 / Uta-Net）", "",
             "每格是该曲命中该规则的行数（自动检测）。振假名来自 Uta-Net 的人工标注。", "",
             "| 曲 / 歌手 | " + " | ".join(all_rules) + " |",
             "|---|" + "---|" * len(all_rules)]
    for k, m in matrix.items():
        lines.append(f"| {k} | " + " | ".join(str(m.get(r, 0)) for r in all_rules) + " |")

    totals = {r: sum(m.get(r, 0) for m in matrix.values()) for r in all_rules}
    lines += ["", "## 规则总量", "", "| 规则 | 命中行数 |", "|---|---|"]
    for r in all_rules:
        lines.append(f"| {r} | {totals[r]} |")

    zero = [r for r in all_rules if totals[r] == 0]
    lines += ["", "## 结论", ""]
    lines.append("- 整表为 0 的规则：" + "、".join(zero) if zero else "- 所有规则在歌词域都有覆盖")
    lines.append("- 官方罗马音存在 `romaji_official`，可用于校验转写层")
    lines.append("- 行数少的曲子样本偏弱，评测时按行数加权")
    (REPORTS / "lyrics_coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n歌词域：{len(records)} 行 / {len(matrix)} 首")


def used_urls(include_test: bool = True) -> set[str]:
    """评测集已经用过的歌（gold + 可选 holdout），拿来做排除。"""
    out: set[str] = set()
    names = ["lyrics.jsonl", "lyrics_gen.jsonl"] + (["lyrics_test.jsonl"] if include_test else [])
    for name in names:
        p = GOLD / name
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    out.add(json.loads(ln).get("url"))
    return out


def ranking_pool(limit: int = 100) -> list[str]:
    html = get(RANKING, tries=3, timeout=90)
    links: list[str] = []
    for m in re.finditer(r'href="(/lyric/[a-z]{2}\d+/)"', html):
        u = "https://utaten.com" + m.group(1)
        if u not in links:
            links.append(u)
        if len(links) >= limit:
            break
    return links


def fetch_page(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    cache = CACHE / f"{slug}.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    page = get(url, tries=3, timeout=90)
    cache.write_text(page, encoding="utf-8")
    time.sleep(0.8)
    return page


def build_holdout(want: int = 20, cap: int = 80) -> None:
    """留出集：抓评测集没唱过的歌，只用来报数，不参与调参。"""
    skip = used_urls()
    pool = [u for u in ranking_pool() if u not in skip]
    print(f"可用 {len(pool)} 首，取前 {want}")
    titles = {json.loads(l).get("title") for f in ("lyrics.jsonl",)
              for l in (GOLD / f).read_text(encoding="utf-8").splitlines() if l.strip()}

    records = []
    for i, url in enumerate(pool[:want], 1):
        slug = url.rstrip("/").split("/")[-1]
        try:
            page = fetch_page(url)
        except Exception as e:
            print(f"[{i}] × {slug}: {e}")
            continue
        title, artist = meta_of(page, slug)
        if title in titles:
            continue
        used, rules = 0, {}
        for ln, ro in parse_page(page):
            if used >= cap:
                break
            if len(ln) < 3 or len(ln) > cap:
                continue
            text, spans = to_spans(ln)
            if not spans or any(text[s["start"]:s["end"]] != s["base"] for s in spans):
                continue
            lab = label_line(text, spans)
            for r in lab["rules"]:
                rules[r] = rules.get(r, 0) + 1
            records.append({
                "id": f"jpop-test-{slug}-{used:03d}", "source": "utaten",
                "domain": "lyrics", "split": "test",
                "title": title, "artist": artist, "url": url,
                "text": text, "spans": spans, "romaji_official": ro,
                "rules": lab["rules"], "primary": lab["primary"],
            })
            used += 1
        print(f"[{i}] {title} / {artist}  +{used} 行")

    out = GOLD / "lyrics_test.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n留出集：{len(records)} 行 / {len({r['title'] for r in records})} 首 "
          f"/ {sum(len(r['spans']) for r in records)} span → {out.relative_to(ROOT)}")


def build_resource(songs: int = 60) -> None:
    """语料表：从非评测歌里统计「词形 → 读音: 次数」。"""
    skip = used_urls()
    pool = [u for u in ranking_pool() if u not in skip]
    print(f"榜单可用 {len(pool)} 首，取前 {songs}")
    table: dict[str, dict[str, int]] = {}
    for i, url in enumerate(pool[:songs], 1):
        slug = url.rstrip("/").split("/")[-1]
        try:
            page = fetch_page(url)
        except Exception as e:
            print(f"[{i}] × {slug}: {e}")
            continue
        n = 0
        for line, _ in parse_page(page):
            text, spans = to_spans(line)
            for sp in spans:
                base, ruby = sp["base"], sp["ruby"]
                if not base or not ruby or len(base) > 8:
                    continue
                table.setdefault(base, {})
                table[base][ruby] = table[base].get(ruby, 0) + 1
                n += 1
        if n:
            print(f"[{i}] +{n} 对（累计 {len(table)} 词形）")

    out = CORPUS / "utaten_resource.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    total = sum(sum(v.values()) for v in table.values())
    print(f"\n资源表：{len(table)} 词形 / {total} 次出现 / "
          f"{sum(1 for v in table.values() if len(v) > 1)} 个多读音 → {out.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30, help="gold 模式：抓前 N 首")
    ap.add_argument("--cap", type=int, default=80, help="每首最多取多少行")
    ap.add_argument("--holdout", action="store_true", help="构建留出集")
    ap.add_argument("--resource", action="store_true", help="构建词→读音语料表")
    ap.add_argument("--holdout-size", type=int, default=20)
    ap.add_argument("--songs", type=int, default=60, help="resource 模式：抓多少首")
    a = ap.parse_args()

    if a.holdout:
        build_holdout(a.holdout_size, a.cap)
    elif a.resource:
        build_resource(a.songs)
    else:
        build_gold(a.top, a.cap)


if __name__ == "__main__":
    main()
