#!/usr/bin/env python3
"""把标注结果渲染成自包含网页。两种模式：

  --songs アイドル 怪物     从 eval/gold/lyrics.jsonl 取若干首（标签页切换）
  --pair demo/src/gunjou.txt  读「日文行 / 中文行」交替的文件（单首长页）
  --text demo/src/xxx.txt     纯日文文本（无译文）

用法:
  python3 tools/render.py --songs アイドル 怪物
  python3 tools/render.py --pair demo/src/gunjou.txt --title 群青
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from tools.common import run_all, segments_of
from tools.common import DEMO_OUT, DEMO_SRC, GOLD, ROOT

CSS = """
:root{--bg:#0f1115;--fg:#e9e7e4;--dim:#878c95;--a:#63c6a3;--c:#c8843f;--line:#20242b;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:34px 32px 16px;text-align:center;border-bottom:1px solid var(--line)}
h1{margin:0 0 6px;font-size:24px;font-weight:600;letter-spacing:.05em}
.sub{color:var(--dim);font-size:13px;letter-spacing:.04em}
.wrap{max-width:780px;margin:0 auto;padding:28px 32px 90px}
.bar{display:flex;gap:18px;flex-wrap:wrap;justify-content:center;margin:0 0 26px;font-size:12px;color:var(--dim)}
.bar label{cursor:pointer;user-select:none}
.bar input{vertical-align:-2px;margin-right:5px}
.tab{padding:6px 13px;border-radius:999px;background:#1b1e24;color:var(--dim);cursor:pointer;font-size:13px;border:1px solid transparent}
.tab.on{background:#243040;color:#fff;border-color:#31465f}
.song{display:none}.song.on{display:block}
.stats{color:var(--dim);font-size:12px;text-align:center;margin:0 0 22px}
.stats b{color:var(--fg)}
.jp{font-size:21px;line-height:2.15;letter-spacing:.02em;margin:0 0 2px}
.cn{font-size:13px;color:var(--dim);line-height:1.8;margin:0 0 14px}
.cn.hidden{display:none}
ruby{ruby-position:over}
rt{font-size:.5em;color:var(--a);letter-spacing:.04em}
/* 底色永远是原文色；只有 ruby 的颜色表示档位
   A 绿 · AB 琥珀 · B 灰 */
.ab rt{color:var(--c)}
.rb rt{color:var(--dim)}
.cd{position:relative;cursor:help;border-bottom:1px dotted var(--dim)}
.cd::after{content:attr(data-tip);position:absolute;left:50%;top:100%;transform:translateX(-50%);
  background:#1b1f26;color:#e9e7e4;border:1px solid #2b313a;border-radius:6px;
  padding:3px 8px;font-size:12px;white-space:nowrap;opacity:0;pointer-events:none;
  transition:opacity .12s;z-index:9}
.cd:hover::after,.cd:focus::after{opacity:1}
.cd.picked{border-bottom-color:var(--a)}
.cd.picked rt{color:var(--a)}
.cd.picked::before{content:"✎";position:absolute;top:-.9em;right:-.5em;font-size:10px;color:var(--a)}
.menu{position:absolute;z-index:20;background:#171b21;border:1px solid #2b313a;border-radius:8px;
  padding:4px;display:flex;flex-direction:column;gap:2px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.menu button{background:none;border:0;color:#e9e7e4;font-size:13px;padding:4px 12px;border-radius:5px;
  cursor:pointer;text-align:left;font-family:inherit}
.menu button:hover{background:#243040}
.menu button.on{color:var(--a)}
#panel{border:1px solid #232830;border-radius:10px;margin:0 0 24px;background:#14181e}
#panel summary{cursor:pointer;padding:12px 14px;font-size:13px;color:var(--dim);letter-spacing:.04em;
  list-style:none;user-select:none}
#panel summary::-webkit-details-marker{display:none}
#panel summary::before{content:"▸ ";display:inline-block;transition:transform .15s}
#panel[open] summary::before{transform:rotate(90deg)}
#panel summary:hover{color:var(--fg)}
#panel-body{padding:0 14px 12px}
#panel .row2{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:5px 0;border-top:1px solid #1c2129}
#panel .row2:first-of-type{border-top:0}
#panel .base{min-width:6em;font-size:15px}
#panel .cnt{color:var(--dim);font-size:11px;min-width:3.5em}
#panel .opt{background:#1b2129;border:1px solid #262d36;color:#cfd3d8;border-radius:999px;
  padding:3px 10px;font-size:12px;cursor:pointer;font-family:inherit}
#panel .opt:hover{border-color:var(--a);color:var(--a)}
#panel .opt.on{background:#20323d;border-color:var(--a);color:var(--a)}
#panel .opt.reset{margin:0 0 8px;border-color:#3a2a2a;color:#c98a8a}
#panel .opt.reset:hover{border-color:#c98a8a;color:#e9a3a3}
.c{border-bottom:1px dotted var(--c);cursor:help}
.c.hidden{border-bottom:none}
footer{color:var(--dim);font-size:12px;text-align:center;line-height:1.9;margin-top:36px}
"""

JS = """
function pick(id,btn){
  document.querySelectorAll('.song').forEach(s=>s.classList.toggle('on',s.id===id));
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b===btn));
}
// 本地保存：按页面标题区分（同一篇文章刷新后仍在）
const STORE_KEY = 'nihongo-acc:corrections:' + (document.title || location.pathname);
function loadStore(){ try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); } catch(e){ return {}; } }
function saveStore(m){ try { localStorage.setItem(STORE_KEY, JSON.stringify(m)); } catch(e){} }

function resetAll(){
  document.querySelectorAll('.cd').forEach(el => {
    const rt = el.querySelector('rt');
    if (rt && el.dataset.orig) rt.textContent = el.dataset.orig;
    el.classList.remove('picked');
    if (el.dataset.orig) el.dataset.cur = el.dataset.orig;
  });
  try { localStorage.removeItem(STORE_KEY); } catch(e){}
  buildPanel();
}

function restoreStore(){
  const saved = loadStore();
  const partsOf = {};
  document.querySelectorAll('.cd').forEach(el => {
    if (!partsOf[el.dataset.base]) partsOf[el.dataset.base] = JSON.parse(el.dataset.parts || '[]');
  });
  for (const [key, reading] of Object.entries(saved)) {
    if (key.startsWith('w:')) {
      const word = key.slice(2);
      const parts = (partsOf[word] || []).find(x => x.r === reading)?.p || null;
      applyWord(word, reading, parts);
    }
  }
  for (const [key, reading] of Object.entries(saved)) {
    if (!key.startsWith('o:')) continue;
    const occ = key.slice(2);
    const el = document.querySelector(`.cd[data-occ="${occ}"]`);
    const parts = el ? (JSON.parse(el.dataset.parts || '[]').find(x => x.r === reading)?.p || null) : null;
    applyOcc(occ, reading, parts);
  }
}

// 把某个整词的读音应用到它所有片段（parts 逐片对应）
function paint(els, reading, parts, persistKey){
  els.forEach((el, i) => {
    const rt = el.querySelector('rt');
    if (!rt) return;
    rt.textContent = parts ? (parts[i] || reading) : reading;
    el.classList.add('picked');
    el.dataset.cur = reading;
  });
  if (persistKey) { const m = loadStore(); m[persistKey] = reading; saveStore(m); }
}

// 正文里点：只改这一处（同一个 word 出现的几个片段一起改）
function applyOcc(occ, reading, parts){
  const els = [...document.querySelectorAll(`.cd[data-occ="${occ}"]`)];
  paint(els, reading, parts, 'o:' + occ);
  syncPanel(els[0]?.dataset.base, reading);
}

// 面板里点：改这一页这个词的所有出现
function applyWord(word, reading, parts){
  const all = [...document.querySelectorAll(`.cd[data-base="${word}"]`)].filter(e => e.offsetParent !== null);
  const byOcc = new Map();
  all.forEach(el => {
    if (!byOcc.has(el.dataset.occ)) byOcc.set(el.dataset.occ, []);
    byOcc.get(el.dataset.occ).push(el);
  });
  byOcc.forEach(els => paint(els, reading, parts, null));
  paint(all, reading, parts, 'w:' + word);   // 只在第一遍后统一写一次存储
  syncPanel(word, reading);
}

function syncPanel(word, reading){
  document.querySelectorAll('#panel .row2').forEach(row => {
    if (row.dataset.word !== word) return;
    row.querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o.dataset.r === reading));
  });
}

function buildPanel(){
  const panel = document.getElementById('panel');
  if (!panel) return;
  const groups = new Map();
  document.querySelectorAll('.cd').forEach(el => {
    if (el.offsetParent === null) return;          // 隐藏的标签页跳过
    const base = el.dataset.base || '';
    if (!base) return;
    if (!groups.has(base)) groups.set(base, {cands: (el.dataset.cands||'').split('|'), els: []});
    groups.get(base).els.push(el);
  });
  const body = document.getElementById('panel-body');
  const sum = panel.querySelector('summary');
  if (!groups.size) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  sum.textContent = `B 档校正 · ${groups.size} 个词，点一下改所有出现`;
  body.innerHTML = '';
  const reset = document.createElement('button');
  reset.className = 'opt reset'; reset.textContent = '全部重置';
  reset.onclick = ev => { ev.stopPropagation(); resetAll(); };
  body.appendChild(reset);
  for (const [base, g] of groups) {
    const row = document.createElement('div'); row.className = 'row2'; row.dataset.word = base;
    const b = document.createElement('span'); b.className = 'base'; b.textContent = base;
    const c = document.createElement('span'); c.className = 'cnt'; c.textContent = g.els.length + ' 处';
    row.append(b, c);
    for (const cand of g.cands) {
      const btn = document.createElement('button');
      btn.className = 'opt'; btn.textContent = cand; btn.dataset.r = cand;
      const cur = g.els[0].querySelector('rt')?.textContent;
      if (cand === cur) btn.classList.add('on');
      btn.onclick = ev => {
        ev.stopPropagation();
        const parts = JSON.parse(g.els[0].dataset.parts || '[]').find(x => x.r === cand)?.p || null;
        applyWord(base, cand, parts);
      };
      row.appendChild(btn);
    }
    body.appendChild(row);
  }
}
window.addEventListener('load', () => { buildPanel(); restoreStore(); });

function tgl(cls,on){document.querySelectorAll('.'+cls).forEach(e=>e.classList.toggle('hidden',!on))}

// 候选选择：点一下 B 档片段 → 弹菜单 → 换读音（只改这句的显示）
document.addEventListener('click', e => {
  const cd = e.target.closest('.cd');
  document.querySelectorAll('.menu').forEach(m => m.remove());
  if (!cd) return;
  e.preventDefault();
  const cands = (cd.dataset.cands || '').split('|').filter(Boolean);
  if (cands.length < 2) return;
  const partsMap = {};
  try { (JSON.parse(cd.dataset.parts || '[]') || []).forEach(x => partsMap[x.r] = x.p); } catch (err) {}
  const menu = document.createElement('div');
  menu.className = 'menu';
  for (const c of cands) {
    const b = document.createElement('button');
    b.textContent = c; b.dataset.r = c;
    if (c === (cd.querySelector('rt')?.textContent || '')) b.classList.add('on');
    b.onclick = ev => {
      ev.stopPropagation();
      applyOcc(cd.dataset.occ, c, partsMap[c] || null);
      menu.remove();
    };
    menu.appendChild(b);
  }
  document.body.appendChild(menu);
  const r = cd.getBoundingClientRect();
  menu.style.left = Math.max(8, r.left + window.scrollX) + 'px';
  menu.style.top = (r.bottom + window.scrollY + 4) + 'px';
});
"""


def render_line(line: str, segs: list[dict], line_no: int = 0) -> str:
    parts, pos = [], 0
    for seg in segs:
        if seg["start"] > pos:
            parts.append(html.escape(line[pos:seg["start"]]))
        base = html.escape(seg["base"])
        if seg["level"] == "A" and seg.get("ruby"):
            parts.append(f"<ruby>{base}<rt>{html.escape(seg['ruby'])}</rt></ruby>")
        elif seg["level"] == "AB" and seg.get("ruby"):
            parts.append(f'<ruby class="ab">{base}<rt>{html.escape(seg["ruby"])}</rt></ruby>')
        elif seg["level"] == "B" and seg.get("ruby"):
            cands = seg.get("cands") or []
            if len(cands) >= 2:
                tip = html.escape(" / ".join(cands))
                menu = html.escape("|".join(cands))
                parts.append(f'<span class="cd" tabindex="0" data-tip="{tip}" '
                             f'data-cands="{menu}" data-base="{html.escape(seg.get("wordbase") or seg["base"])}" '
                             f'data-parts="{html.escape(json.dumps(seg.get("cand_parts") or [], ensure_ascii=False))}" '
                             f'data-occ="{line_no}-{seg.get("word", 0)}" '
                             f'data-cur="{html.escape(seg["ruby"])}" data-orig="{html.escape(seg["ruby"])}">'
                             f'<ruby class="rb">{base}<rt>{html.escape(seg["ruby"])}</rt></ruby>'
                             f'</span>')
            else:
                parts.append(f'<ruby class="rb">{base}<rt>{html.escape(seg["ruby"])}</rt></ruby>')
        elif seg["level"] == "C":
            reason = seg.get("reason") or {}
            label = reason.get("label", "") if isinstance(reason, dict) else str(reason)
            parts.append(f'<span class="c" title="{html.escape(label)}">{base}</span>')
        else:
            parts.append(base)
        pos = seg["end"]
    if pos < len(line):
        parts.append(html.escape(line[pos:]))
    return "".join(parts)


def build(title: str, artist: str, blocks: list[str], stats: str, tabs: str = "") -> str:
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header><h1>{html.escape(title)}</h1><div class="sub">{html.escape(artist)}</div></header>
<div class="wrap"><details id="panel"><summary>B 档校正</summary><div id="panel-body"></div></details>
<div class="bar">{tabs}
<label><input type="checkbox" checked onchange="tgl('cn',this.checked)">中文</label>
<label><input type="checkbox" checked onchange="tgl('c',this.checked)">弃权标记</label>
</div>
<div class="stats">{stats}</div>
{"".join(blocks)}
<footer>振假名由本地词典 + 词表 + 规则生成，未使用在线服务。<br>
橙点 = 主动弃权（规则判断不可靠），不是“没有读音”。</footer>
</div><script>{JS}</script></body></html>"""


def mode_songs(names: list[str]) -> tuple[str, str, list[str], str, str]:
    recs = [json.loads(l) for l in (GOLD / "lyrics.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by: dict[str, list[dict]] = {}
    for r in recs:
        by.setdefault(r["title"], []).append(r)

    tabs, blocks, total_a, total_c = [], [], 0, 0
    for i, name in enumerate(names):
        if name not in by:
            print(f"× 没有这首歌：{name}")
            continue
        rows = by[name]
        resps = run_all([r["text"] for r in rows])
        paras = []
        for rec, resp in zip(rows, resps):
            segs = segments_of(resp)
            total_a += sum(1 for s in segs if s["level"] == "A" and s.get("ruby"))
            total_c += sum(1 for s in segs if s["level"] == "C")
            paras.append(f'<div class="jp">{render_line(rec["text"], segs, len(paras))}</div>')
        sid = f"song{i}"
        tabs.append(f'<div class="tab{" on" if i == 0 else ""}" onclick="pick(\'{sid}\',this)">{html.escape(name)}</div>')
        blocks.append(f'<section class="song{" on" if i == 0 else ""}" id="{sid}">{"".join(paras)}</section>')

    stats = f"标注 <b>{total_a}</b> 处 · 弃权 <b>{total_c}</b> 处"
    return (" · ".join(names), "Uta-Net 官方振假名对照", blocks, stats, "".join(tabs))


def mode_pair(path: Path) -> tuple[str, str, list[str], str, str]:
    raw = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pairs = [(raw[i], raw[i + 1] if i + 1 < len(raw) else "") for i in range(0, len(raw), 2)]
    resps = run_all([p[0] for p in pairs])

    blocks, total_a, total_c = [], 0, 0
    for (jp, cn), resp in zip(pairs, resps):
        segs = segments_of(resp)
        total_a += sum(1 for s in segs if s["level"] == "A" and s.get("ruby"))
        total_c += sum(1 for s in segs if s["level"] == "C")
        blocks.append(f'<div class="jp">{render_line(jp, segs, len(blocks))}</div>'
                      f'<div class="cn">{html.escape(cn)}</div>')
    stats = f"{len(pairs)} 行 · 标注 <b>{total_a}</b> 处 · 弃权 <b>{total_c}</b> 处"
    return (path.stem, "", blocks, stats, "")


def mode_text(path: Path) -> tuple[str, str, list[str], str, str]:
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    resps = run_all(lines)
    blocks, total_a, total_c = [], 0, 0
    for jp, resp in zip(lines, resps):
        segs = segments_of(resp)
        total_a += sum(1 for s in segs if s["level"] == "A" and s.get("ruby"))
        total_c += sum(1 for s in segs if s["level"] == "C")
        blocks.append(f'<div class="jp">{render_line(jp, segs, len(blocks))}</div>')
    stats = f"{len(lines)} 行 · 标注 <b>{total_a}</b> 处 · 弃权 <b>{total_c}</b> 处"
    return (path.stem, "", blocks, stats, "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", nargs="+")
    ap.add_argument("--pair")
    ap.add_argument("--text")
    ap.add_argument("--title")
    ap.add_argument("--artist", default="")
    ap.add_argument("-o", "--out", help="默认：--pair 用源文件名，--songs 用 index.html")
    a = ap.parse_args()

    if a.text:
        title, artist, blocks, stats, tabs = mode_text(ROOT / a.text)
        artist = a.artist or artist
    elif a.pair:
        title, artist, blocks, stats, tabs = mode_pair(ROOT / a.pair)
        artist = a.artist or artist
    elif a.songs:
        title, artist, blocks, stats, tabs = mode_songs(a.songs)
    else:
        ap.error("要么 --songs，要么 --pair")

    page = build(a.title or title, artist, blocks, stats, tabs)
    if a.out:
        out = Path(a.out) if Path(a.out).is_absolute() else ROOT / a.out
    elif a.pair or a.text:
        out = DEMO_OUT / (Path(a.pair or a.text).stem + ".html")
    else:
        out = DEMO_OUT / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"{out.relative_to(ROOT)} · {stats.replace('<b>', '').replace('</b>', '')}")


if __name__ == "__main__":
    main()
