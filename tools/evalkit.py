#!/usr/bin/env python3
"""评测工具集：系统层打分 / 上限分析 / 弃权统计 / 溢出抽检。

    python tools/evalkit.py run [--annotator CMD] [--gold FILE] [--lyrics] [--limit N]
    python tools/evalkit.py ceiling
    python tools/evalkit.py stats
    python tools/evalkit.py audit [--n 30] [--seed 11]

原来分成 eval/ceiling/stats/audit 四个文件，它们共用 load_gold 与标注器外壳，
合并成一个入口。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from common import (CORPUS, CURATED, GOLD, REPORTS, ROOT, TABLES, Annotator,
                    load_gold, normalize, run_all, segments_of)
from nihonco_yomi.kana import kata_to_hira


#!/usr/bin/env python3
"""评测：拿 gold.jsonl 跑标注器，按规则分组算 precision / coverage。

标注器通过 stdio 调用（JSON Lines），这样评测和目标服务用同一个契约：

    发送  {"text": "...", "options": {...}}
    接收  {"segments": [{"base","ruby","level","start","end"}], "romaji": {...}, "keys": {...}}

用法:
    # 没有标注器时先跑空实现，验证管线通不通
    python3 tools/evalkit.py run --dummy

    # 正式跑
    python3 tools/evalkit.py run --annotator "python3 -m nihonco_yomi.annotate --stdio"

指标:
    precision = 判对的已标注 span / 全部已标注 span   ← 核心指标（目标 ≥99.5%）
    coverage  = 已标注的 gold span / 全部 gold span   ← 覆盖率（目标 ≥85%）
    exact     = 读音完全一致的 span（与 precision 同义，单列便于观察）
"""




PROSE = GOLD / "gold.jsonl"

KANJI = re.compile(r"[\u4e00-\u9fff\u3005\u3006]")




def run_dummy(text: str) -> dict:
    """空标注器：不产出任何 ruby，用来验证管线（不依赖 fugashi）。"""
    return {"lines": [{"text": text, "segments": []}]}




def predicted_spans(resp: dict) -> list[dict]:
    """响应是 {lines:[{segments:[...]}]}；单行返回 {segments:[...]} 也兼容。"""
    out = []
    for line in resp.get("lines") or []:
        for s in line.get("segments") or []:
            if s.get("ruby"):
                out.append(s)
    if not out:
        out = [s for s in (resp.get("segments") or []) if s.get("ruby")]
    return out


def score(gold: list[dict], annotate, responses: list[dict] | None = None) -> dict:
    """按 gold span 对齐打分。

    对每个 gold span：
      取所有与它重叠的预测 segment，把 base/ruby 依次拼起来比较——
      这样「掃除機 / そうじき」和「掃除+機 / そうじ+き」视为同一个结果，
      避免把分词边界差异误判成读音错误。

    指标：
      precision = 判对 / (判对 + 判错)      只在 gold 覆盖的地方可验证
      coverage  = 判对 / gold span 总数
      extra     = 标了但 gold 没覆盖的 segment 数（不可验证，单独报，抽样人工看）
    """
    per_level = defaultdict(lambda: {"gold": 0, "correct": 0, "wrong": 0})
    per_rule = defaultdict(lambda: {"gold": 0, "correct": 0, "wrong": 0, "over": 0, "under": 0, "miss": 0, "extra": 0})
    per_domain = defaultdict(lambda: {"gold": 0, "correct": 0, "wrong": 0, "over": 0, "under": 0, "miss": 0, "extra": 0})
    totals = {"gold": 0, "correct": 0, "wrong": 0, "over": 0, "under": 0, "miss": 0, "extra": 0}
    failures = []

    for idx, rec in enumerate(gold):
        prim = rec.get("primary") or "R1"
        domain = rec.get("domain") or "prose"
        gspans = rec.get("spans") or []
        pspans = predicted_spans(responses[idx] if responses is not None else annotate(rec["text"]))

        def bump(bucket, key):
            bucket[key] += 1

        used = set()
        for g in gspans:
            cover = []
            for i, p in enumerate(pspans):
                ps, pe = p.get("start"), p.get("end")
                if ps is None or pe is None:
                    continue
                if ps < g["end"] and pe > g["start"]:
                    cover.append((i, p))
            bump(totals, "gold"); bump(per_rule[prim], "gold"); bump(per_domain[domain], "gold")

            if not cover:
                bump(totals, "miss"); bump(per_rule[prim], "miss"); bump(per_domain[domain], "miss")
                per_level["C"]["gold"] += 1
                continue

            cover.sort(key=lambda x: x[1]["start"])
            lvs = sorted({p.get("level") for _, p in cover if p.get("ruby")})
            lvkey = lvs[0] if len(lvs) == 1 else "mixed"
            per_level[lvkey]["gold"] += 1
            for i, _ in cover:
                used.add(i)
            pred_ruby = normalize("".join(p.get("ruby") or "" for _, p in cover))
            pred_base = "".join(p.get("base") or "" for _, p in cover)
            g_ruby = normalize(g["ruby"])

            if pred_ruby == g_ruby:
                per_level[lvkey]["correct"] += 1
                bump(totals, "correct"); bump(per_rule[prim], "correct"); bump(per_domain[domain], "correct")
            elif pred_base.startswith(g["base"]) and pred_ruby.startswith(g_ruby):
                # 我们把 ruby 覆盖到了更大的词上（gold 只标了其中一部分）
                bump(totals, "over"); bump(per_rule[prim], "over"); bump(per_domain[domain], "over")
            elif g["base"].startswith(pred_base) and g_ruby.startswith(pred_ruby):
                bump(totals, "under"); bump(per_rule[prim], "under"); bump(per_domain[domain], "under")
            else:
                per_level[lvkey]["wrong"] += 1
                bump(totals, "wrong"); bump(per_rule[prim], "wrong"); bump(per_domain[domain], "wrong")
                if len(failures) < 15:
                    failures.append({
                        "rule": prim, "text": rec["text"][:40],
                        "gold": f'{g["base"]}→{g["ruby"]}',
                        "pred": f'{pred_base}→{pred_ruby}',
                    })

        for i, p in enumerate(pspans):
            if i not in used:
                bump(totals, "extra"); bump(per_rule[prim], "extra"); bump(per_domain[domain], "extra")

    verifiable = totals["correct"] + totals["wrong"]

    def pct(a, b):
        return f"{100.0 * a / b:.1f}%" if b else "—"

    return {
        "totals": totals,
        "per_rule": per_rule,
        "per_domain": per_domain,
        "per_level": per_level,
        "failures": failures,
        "report": {
            "precision": pct(totals["correct"], verifiable),
            "coverage": pct(totals["correct"], totals["gold"]),
            "extra": totals["extra"],
        },
    }


def cmd_run(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(PROSE))
    ap.add_argument("--annotator", help="stdio 标注器命令，例如 'python3 -m nihonco_yomi.annotate --stdio'")
    ap.add_argument("--dummy", action="store_true", help="用空标注器验证管线")
    ap.add_argument("--lyrics", action="store_true", help="同时加载歌词开发集")
    ap.add_argument("--exclude-latin", action="store_true",
                    help="忽略 base 含拉丁/卢恩字符的 gold span（不属于汉字标注范围）")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    files = [Path(a.gold)]
    if a.lyrics:
        files.append(GOLD / "lyrics.jsonl")
    gold = load_gold(files)
    if a.exclude_latin:
        import re as _re
        for rec in gold:
            rec["spans"] = [g for g in rec["spans"]
                            if not _re.search(r"[A-Za-zᚠ-᛿]", g["base"])]
    if a.limit:
        gold = gold[: a.limit]
    print(f"gold：{len(gold)} 条")

    if a.dummy or not a.annotator:
        annotate = run_dummy
        print("模式：dummy（全部不标）")
    else:
        ann = Annotator(a.annotator)
        annotate = ann.annotate
        print(f"模式：{a.annotator}")

    res = score(gold, annotate)
    t = res["totals"]
    print("\n=== 总览 ===")
    print(f"  gold span  {t['gold']}")
    print(f"  判对+判错  {t['correct'] + t['wrong']}（gold 覆盖处）")
    print(f"  判对       {t['correct']}")
    print(f"  判错       {t['wrong']}")
    print(f"  对齐差     {t['over'] + t['under']}（我们覆盖更大词 / 更小词，读音本身不冲突）")
    print(f"  漏标       {t['miss']}")
    print(f"  溢出       {t['extra']}（gold 没覆盖，不可验证）")
    print(f"  precision  {res['report']['precision']}  ← 只在可验证处计算")
    print(f"  coverage   {res['report']['coverage']}")

    print("\n=== 按档 ===")
    print(f"  {'档':<6}{'gold':>6}{'对':>6}{'错':>6}   precision   coverage")
    for lv in ("A", "AB", "B", "C"):
        d = res["per_level"].get(lv)
        if not d:
            continue
        right, wrong, g = d["correct"], d["wrong"], d["gold"]
        prec = f"{right/(right+wrong):.1%}" if right + wrong else "—"
        print(f"  {lv:<6}{g:>6}{right:>6}{wrong:>6}   {prec:<10}  {right/max(1,res['totals']['gold']):.1%}")
    mix = res["per_level"].get("mixed")
    if mix:
        print(f"  （另有 {mix['gold']} 个 span 被不同档的片段拼接覆盖，不属任何一档）")

    print("\n=== 按规则 ===")
    print(f"  {'规则':<6}{'gold':>6}{'可判':>6}{'对':>6}{'错':>6}{'漏':>5}{'溢出':>7}{'precision':>11}{'coverage':>10}")
    for rule in sorted(res["per_rule"]):
        b = res["per_rule"][rule]
        p = f"{100.0*b['correct']/(b['correct']+b['wrong']):.1f}%" if (b['correct']+b['wrong']) else "—"
        c = f"{100.0*b['correct']/b['gold']:.1f}%" if b["gold"] else "—"
        print(f"  {rule:<6}{b['gold']:>6}{b['correct']+b['wrong']:>6}{b['correct']:>6}{b['wrong']:>6}"
              f"{b['miss']:>5}{b['extra']:>7}{p:>11}{c:>10}")

    print("\n=== 按域 ===")
    for dom in sorted(res["per_domain"]):
        b = res["per_domain"][dom]
        v = b["correct"] + b["wrong"]
        p = f"{100.0*b['correct']/v:.1f}%" if v else "—"
        c = f"{100.0*b['correct']/b['gold']:.1f}%" if b["gold"] else "—"
        print(f"  {dom:<8} gold={b['gold']:<5} 可判={v:<5} 对={b['correct']:<5} 错={b['wrong']:<5} precision={p:<7} coverage={c}")

    if res["failures"]:
        print("\n=== 失败样例（前 20）===")
        for f in res["failures"]:
            print(f"  [{f['rule']}] {f['text'][:40]}")
            print(f"        gold={f['gold']}  pred={f['pred']}")


#!/usr/bin/env python3
"""测量评测集的上限：把误差拆成「资料里没有」与「我们选错」。

判定与 run 子命令完全一致（按 gold span 取重叠的预测 segment，拼起来比读音），
否则两边的 precision 会对不上。

输出：
  A 现状        标注器的实测
  B 完美弃权    假设能精确识别每个错误并弃权 → precision 100%
  C 词典上界    假设抄遍资料（UniDic ∪ JMdict ∪ 熟字訓表）

用法: python3 tools/evalkit.py ceiling
"""






def cmd_ceiling(argv=None) -> None:
    readings = json.loads((TABLES / "jmdict_readings.json").read_text(encoding="utf-8"))
    jukujikun = json.loads((TABLES / "jmdict_kanjidic2_jukujikun.json").read_text(encoding="utf-8"))

    import fugashi
    import unidic_lite

    tagger = fugashi.Tagger(unidic_lite.DICDIR)

    def unidic_reading(surface: str) -> str:
        try:
            ws = list(tagger(surface))
            if len(ws) == 1:
                return kata_to_hira(str(ws[0].feature[6] or ""))
        except Exception:
            pass
        return ""

    gold = load_gold([GOLD / "gold.jsonl", GOLD / "lyrics.jsonl"])
    from common import run_all, segments_of
    responses = run_all([r["text"] for r in gold])

    st = {"gold": 0, "correct": 0, "wrong": 0, "miss": 0,
          "reach": 0, "reach_correct": 0, "reach_wrong": 0, "reach_miss": 0,
          "unreach": 0, "unreach_correct": 0, "unreach_wrong": 0, "unreach_miss": 0}
    samples = []

    for rec, resp in zip(gold, responses):
        pspans = [s for s in segments_of(resp) if s.get("ruby")]

        for g in rec["spans"]:
            st["gold"] += 1
            want = normalize(g["ruby"])

            # 与 eval 一致：取重叠的预测 segment，拼起来比
            cover = sorted(
                [p for p in pspans
                 if p.get("start") is not None and p.get("end") is not None
                 and p["start"] < g["end"] and p["end"] > g["start"]],
                key=lambda p: p["start"],
            )
            if not cover:
                ok = None
                st["miss"] += 1
            else:
                pred = normalize("".join(p.get("ruby") or "" for p in cover))
                pred_base = "".join(p.get("base") or "" for p in cover)
                if pred == want:
                    ok = True
                    st["correct"] += 1
                elif pred_base.startswith(g["base"]) and pred.startswith(want):
                    ok = None            # 覆盖更大词，读音不冲突 → 与 eval 一样单列
                    st["align"] = st.get("align", 0) + 1
                elif g["base"].startswith(pred_base) and want.startswith(pred):
                    ok = None
                    st["align"] = st.get("align", 0) + 1
                else:
                    ok = False
                    st["wrong"] += 1

            # 资料里有没有这个读音
            cand = set()
            extra = []
            for src in (readings.get(g["base"]) or []) + (jukujikun.get(g["base"]) or []) + extra:
                cand.add(normalize(src))
            ud = unidic_reading(g["base"])
            if ud:
                cand.add(normalize(ud))
            reach = any(c == want or c.startswith(want) or want.startswith(c) for c in cand)

            bucket = "reach" if reach else "unreach"
            st[bucket] += 1
            if ok is True:
                st[f"{bucket}_correct"] += 1
            elif ok is False:
                st[f"{bucket}_wrong"] += 1
                if not reach and len(samples) < 6:
                    samples.append((g["base"], g["ruby"]))
            else:
                st[f"{bucket}_miss"] += 1
    n = st["gold"]
    p_cur = st["correct"] / max(1, st["correct"] + st["wrong"])
    c_cur = st["correct"] / n
    p_reach = st["reach_correct"] / max(1, st["reach_correct"] + st["reach_wrong"])

    print("=== 表覆盖率 ===")
    print("（衡量：手头的表能解释多少 span。**不是**系统上限——系统还会用"
          "分词器在上下文里的读音。）")
    print()
    print(f"gold span 总数          {n}")
    print(f"  表里能查到读音        {st['reach']:5d}  ({st['reach']/n:.1%})")
    print(f"  表里查不到            {st['unreach']:5d}  ({st['unreach']/n:.1%})")
    print()
    print(f"现状             precision {p_cur:.1%}   coverage {c_cur:.1%}"
          f"   （对齐差 {st.get('align', 0)} 处已排除）")
    print(f"表内可判部分     precision {p_reach:.1%}（{st['reach']} 个 span 上）")
    print()
    print(f"标错 {st['wrong']} 处：表里其实有正确答案 {st['reach_wrong']} 处（选错了），"
          f"表里没有 {st['unreach_wrong']} 处（表没覆盖）")
    if c_cur > st["reach"] / n:
        print(f"\n注意：实际 coverage {c_cur:.1%} 高于表覆盖率 {st['reach']/n:.1%}，"
              "差额来自分词器在上下文里的读音——所以这里没有'上界'可言。")
    if samples:
        print("\n表里查不到的读音（样例）：" + "、".join(f"{b}→{r}" for b, r in samples))


#!/usr/bin/env python3
"""弃权原因统计：我们的 C 到底是因为什么弃的，其中多少是本该标出来的。

用法: python3 tools/evalkit.py stats
"""





def cmd_stats(argv=None) -> None:
    """统计口径与 make eval 一致：直接调用 score()，不再自己算一遍。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", nargs="+",
                    default=[str(GOLD / "lyrics.jsonl"), str(GOLD / "lyrics_test.jsonl"),
                             str(GOLD / "lyrics_gen.jsonl"), str(GOLD / "gold.jsonl")])
    ap.add_argument("--annotator", help="stdio 标注器命令，默认用 annotate.py")
    a = ap.parse_args(argv or [])

    gold = load_gold([Path(x) for x in a.gold])
    from common import DEFAULT_CMD
    ann = Annotator(a.annotator or DEFAULT_CMD)
    annotate = ann.annotate
    resp = [annotate(r["text"]) for r in gold]
    res = score(gold, annotate, responses=resp)
    totals = res["totals"]
    verifiable = totals["correct"] + totals["wrong"]

    print("=== 总览（与 eval 同口径）===")
    print(f"  gold span  {totals['gold']}")
    print(f"  判对+判错  {verifiable}（gold 覆盖处）")
    print(f"  判对       {totals['correct']}")
    print(f"  判错       {totals['wrong']}")
    print(f"  对齐差     {totals['over'] + totals['under']}（覆盖范围不同，读音不冲突）")
    print(f"  漏标       {totals['miss']}")
    print(f"  溢出       {totals['extra']}（gold 没覆盖，不可验证）")
    print(f"  precision  {totals['correct']/max(1,verifiable):.1%}")
    print(f"  coverage   {totals['correct']/max(1,totals['gold']):.1%}")

    # 片段级别与弃权原因需要逐片段看，单独统计（不参与 precision）
    seg_kind, reasons, reason_examples = Counter(), Counter(), defaultdict(list)
    for r in resp:
        for seg in segments_of(r):
            seg_kind[seg["level"]] += 1
            if seg["level"] != "C":
                continue
            rr = seg.get("reason") or {}
            code = rr.get("code") if isinstance(rr, dict) else str(rr)
            label = rr.get("label", "") if isinstance(rr, dict) else str(rr)
            key = f"{code}（{label.split('（')[0]}）" if code else label
            reasons[key] += 1
            if len(reason_examples[key]) < 5:
                reason_examples[key].append(seg["base"])

    tot = sum(seg_kind.values())
    print("\n=== 片段级别 ===")
    for k in ("A", "AB", "B", "K", "C"):
        print(f"  {k}: {seg_kind[k]:>6}  ({seg_kind[k]/max(1,tot):.1%})")
    print(f"  合计 {tot}")

    print("\n=== 按档（gold span 上的 precision）===")
    print(f"  {'档':<6}{'gold':>6}{'对':>6}{'错':>6}   precision")
    for lv in ("A", "AB", "B", "C"):
        d = res["per_level"].get(lv)
        if not d:
            continue
        right, wrong = d["correct"], d["wrong"]
        prec = f"{right/(right+wrong):.1%}" if right + wrong else "—"
        print(f"  {lv:<6}{d['gold']:>6}{right:>6}{wrong:>6}   {prec}")

    print("\n=== 弃权原因 ===")
    for k, n in reasons.most_common():
        print(f"  {k:<22}{n:>5}  例：" + "、".join(reason_examples[k]))


def cmd_audit(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--domain", default="prose")
    a = ap.parse_args(argv)

    gold = load_gold([GOLD / "gold.jsonl", GOLD / "lyrics.jsonl"])
    gold = [r for r in gold if (r.get("domain") or "prose") == a.domain]

    from common import run_all, segments_of
    responses = run_all([r["text"] for r in gold])

    pool = []
    for rec, resp in zip(gold, responses):
        segs = [s for s in segments_of(resp) if s.get("ruby")]
        for s in segs:
            if not any(s["start"] < g["end"] and s["end"] > g["start"] for g in rec["spans"]):
                pool.append({
                    "text": rec["text"],
                    "base": s["base"], "ruby": s["ruby"],
                    "start": s["start"], "end": s["end"],
                    "gold": [f'{g["base"]}→{g["ruby"]}' for g in rec["spans"]],
                })
    print(f"溢出池：{len(pool)} 条（域={a.domain}）")
    sample = random.Random(a.seed).sample(pool, min(a.n, len(pool)))

    out = REPORTS / "audit_pending.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for i, item in enumerate(sample, 1):
            item["id"] = f"audit-{i:03d}"
            item["verdict"] = None
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    for i, item in enumerate(sample, 1):
        ctx = item["text"]
        s, e = item["start"], item["end"]
        marked = ctx[:s] + "【" + ctx[s:e] + "】" + ctx[e:]
        print(f'{i:>2}. {item["base"]} → {item["ruby"]}   | {marked[:64]}')
        print(f'    gold: {" ".join(item["gold"])[:70]}')

    print(f"\n待判条目写入 {out.relative_to(ROOT)}（verdict 留空，判完写回）")



def cmd_patches(argv=None) -> None:
    """审计人工词表（glossary_lyrics.json）在 gold 上是赚还是亏。

    用法: python3 tools/evalkit.py patches [--top 12]
    """
    import nihonco_yomi.annotate as A

    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)

    A.load_tables()
    patch = set(A.GLOSSARY)

    gold = load_gold([GOLD / "gold.jsonl", GOLD / "lyrics.jsonl", GOLD / "lyrics_test.jsonl"])
    resps = run_all([r["text"] for r in gold])

    hit, miss_gold, abstain = 0, 0, 0
    wrong: dict[str, list[tuple[str, str]]] = defaultdict(list)
    right: dict[str, int] = defaultdict(int)

    for rec, resp in zip(gold, resps):
        for seg in segments_of(resp):
            base = seg["base"]
            if base not in patch:
                continue
            g = next((x for x in rec["spans"] if x["base"] == base), None)
            if g is None:
                miss_gold += 1
                continue
            if not seg.get("ruby"):
                abstain += 1
                continue
            if normalize(seg["ruby"]) == normalize(g["ruby"]):
                hit += 1
                right[base] += 1
            else:
                wrong[base].append((g["ruby"], seg["ruby"]))

    total_wrong = sum(len(v) for v in wrong.values())
    print("=== 人工补丁审计 ===")
    print(f"人工词表 {len(patch)} 个词形")
    print(f"gold 有对照：对 {hit} / 错 {total_wrong} / 弃权 {abstain} / 无 gold {miss_gold}")
    if hit + total_wrong:
        print(f"补丁命中处 precision：{hit / (hit + total_wrong):.1%}")

    if wrong:
        print("\n错误明细（按出现次数）：")
        for base, items in sorted(wrong.items(), key=lambda kv: -len(kv[1]))[: a.top]:
            got = {f"{w}→{r}" for w, r in items}
            gold_r = {w for w, _ in items}
            print(f"  {base:<4} 错 {len(items):>2} 次   gold={'/'.join(sorted(gold_r)):<10} "
                  f"我们={'/'.join(sorted(got))}")
    if right:
        print("\n补丁救回的次数（前几名）：")
        for base, n in sorted(right.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {base:<4} 对 {n} 次")
    print("\n判据：错 > 对 的补丁应该删掉，只错 1–2 次的可以留着观察。")




FILES_GOLD = {"prose": "gold.jsonl", "lyrics": "lyrics.jsonl", "test": "lyrics_test.jsonl"}


def cmd_gold_audit(argv=None) -> None:
    """抽检 gold 本身：参考标注是不是真对。

    用法:
        python tools/evalkit.py gold-audit --n 30 --domain lyrics --seed 11
        python tools/evalkit.py gold-audit --summary
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--domain", default="prose", choices=list(FILES_GOLD))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)

    pending = REPORTS / "gold_audit_pending.jsonl"

    if a.summary:
        if not pending.exists():
            print("没有待判文件")
            return
        rows = [json.loads(l) for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
        done = [r for r in rows if r.get("verdict")]
        bad = [r for r in done if r["verdict"] == "bad"]
        print(f"已判 {len(done)} / {len(rows)}，判错 {len(bad)}"
              f"（{len(bad)/max(1,len(done)):.1%}）")
        for r in bad:
            print(f'  {r["base"]}→{r["ruby"]}  | {r["text"][:34]}')
        return

    recs = load_gold([GOLD / FILES_GOLD[a.domain]])
    spans = [(r["text"], g, r.get("primary")) for r in recs for g in r["spans"]]
    sample = random.Random(a.seed).sample(spans, min(a.n, len(spans)))

    with pending.open("w", encoding="utf-8") as f:
        for i, (text, g, prim) in enumerate(sample, 1):
            f.write(json.dumps({"id": f"gold-{i:03d}", "text": text, "base": g["base"],
                                "ruby": g["ruby"], "start": g["start"], "end": g["end"],
                                "rule": prim, "verdict": None}, ensure_ascii=False) + "\n")

    for i, (text, g, prim) in enumerate(sample, 1):
        s0, e0 = g["start"], g["end"]
        print(f'{i:>2}. [{prim}] {g["base"]} → {g["ruby"]:<10} | '
              f'{text[:s0] + "【" + text[s0:e0] + "】" + text[e0:]}'[:70])
    print(f"\n写入 {pending}（{len(sample)} 条）")


COMMANDS = {"run": cmd_run, "ceiling": cmd_ceiling, "stats": cmd_stats,
            "audit": cmd_audit, "patches": cmd_patches,
            "gold-audit": cmd_gold_audit}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
