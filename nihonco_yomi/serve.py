#!/usr/bin/env python3
"""最小的本地标注页：一个进程，一个页面，调 nihongo_acc.Annotator。

    python serve.py            # http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import nihonco_yomi
from .render import segments_html

AN = nihonco_yomi.Annotator()
LOCK = threading.Lock()      # Sudachi tokenizer 不是线程安全的

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>振り仮名标注</title><style>
:root{--bg:#0f1115;--fg:#e9e7e4;--dim:#878c95;--a:#63c6a3;--c:#c8843f}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,"Hiragino Sans",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:26px 26px 70px}
h1{font-size:20px;font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:12px;margin-bottom:16px}
textarea{width:100%;min-height:110px;background:#14181e;color:var(--fg);border:1px solid #262d36;
  border-radius:10px;padding:12px;font-size:15px;line-height:1.8;font-family:inherit;resize:vertical}
button{background:#1b2129;color:#cfd3d8;border:1px solid #2b313a;border-radius:7px;
  padding:5px 11px;font-size:13px;cursor:pointer;font-family:inherit}
button:hover{border-color:var(--a);color:var(--a)}
#go{margin:10px 0 20px}
#lineage{margin:0 0 18px;padding-bottom:14px;border-bottom:1px solid #191d23}
.jp{font-size:21px;line-height:2.1}
.rm{font-size:14px;color:var(--a);margin-top:5px}
.ky{font-size:12px;color:var(--dim);font-family:ui-monospace,Menlo,monospace}
rt{font-size:.5em;color:var(--a)}.ab rt{color:var(--c)}.rb rt{color:var(--dim)}
.cd{position:relative;cursor:pointer;border-bottom:1px dotted var(--c)}
.cd.picked{border-bottom-color:var(--a)}.cd.picked rt{color:var(--a)}
.cd.picked::before{content:"✎";position:absolute;top:-.9em;right:-.5em;font-size:10px;color:var(--a)}
.menu{position:absolute;z-index:30;background:#171b21;border:1px solid #2b313a;border-radius:8px;
  padding:4px;display:flex;flex-direction:column;gap:2px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.menu button{background:none;border:0;color:#e9e7e4;font-size:13px;padding:4px 14px;border-radius:5px;
  cursor:pointer;text-align:left}
.menu button:hover{background:#243040}.menu button.on{color:var(--a)}
.row2:first-of-type{border-top:0}

.opt{background:#1b2129;border:1px solid #262d36;color:#cfd3d8;border-radius:999px;
  padding:3px 10px;font-size:12px;cursor:pointer}
.opt:hover{border-color:var(--a);color:var(--a)}
.opt.on{background:#20323d;border-color:var(--a);color:var(--a)}
.opt.reset{margin:0 0 8px;border-color:#3a2a2a;color:#c98a8a}
.kin{background:#0f1318;border:1px solid #2b313a;color:var(--fg);border-radius:6px;
  padding:3px 8px;font-size:13px;width:7em;font-family:inherit}
.kin.bad{border-color:#c06060}
</style></head><body><div class="wrap">
<h1>振り仮名标注</h1>
<div class="sub">A 绿 · AB 琥珀 · B 灰（点一下改读音，改过的存在本地）</div>
<textarea id="in">私の名は「吉良吉影」、年齢33歳。自宅は杜王町北東部の別荘地帯にあり。結婚はしていない。</textarea>
<button id="go">标注</button>
<div id="out"></div>
<script>
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let TEXT = '', OV = {};
const hash = s => { let h = 5381; for (const c of s) h = ((h << 5) + h + c.codePointAt(0)) | 0; return Math.abs(h).toString(36); };
const ckey = () => 'nihongo-acc:cand:' + hash(TEXT);
const load = () => { try { return JSON.parse(localStorage.getItem(ckey()) || '{}'); } catch(e) { return {}; } };
const save = m => { try { localStorage.setItem(ckey(), JSON.stringify(m)); } catch(e) {} };

function segHTML(seg, li){
  if (!seg.ruby) return seg.level === 'C' ? `<span class="c">${esc(seg.base)}</span>` : esc(seg.base);
  const cls = seg.level === 'AB' ? 'ab' : seg.level === 'B' ? 'rb' : '';
  const inner = `<ruby${cls ? ` class="${cls}"` : ''}>${esc(seg.base)}<rt>${esc(seg.ruby)}</rt></ruby>`;
  if (seg.level === 'B') {
    const parts = esc(JSON.stringify(seg.cand_parts || []));
    return `<span class="cd" data-base="${esc(seg.wordbase || seg.base)}" data-cands="${(seg.cands || []).join('|')}"`
         + ` data-parts="${parts}" data-occ="${li}-${seg.word}" data-orig="${esc(seg.ruby)}">${inner}</span>`;
  }
  return inner;
}
function paint(els, reading, parts, key){
  els.forEach((el, i) => {
    const rt = el.querySelector('rt'); if (!rt) return;
    rt.textContent = parts ? (parts[i] || reading) : (i === 0 ? reading : '');
    el.classList.add('picked');
  });
  if (key) { const m = load(); m[key] = reading; save(m); OV[key] = reading; }
}
function applyOcc(occ, reading, parts){
  const els = [...document.querySelectorAll(`.cd[data-occ="${occ}"]`)];
  paint(els, reading, parts, 'o:' + occ);
}
function markPicked(){
  for (const k of Object.keys(load())) {
    const sel = k.startsWith('o:') ? `.cd[data-occ="${k.slice(2)}"]`
                                   : `.cd[data-base="${k.slice(2)}"]`;
    document.querySelectorAll(sel).forEach(el => el.classList.add('picked'));
  }
}

function restore(){
  const saved = load(), partsOf = {};
  document.querySelectorAll('.cd').forEach(el => {
    if (!partsOf[el.dataset.base]) partsOf[el.dataset.base] = JSON.parse(el.dataset.parts || '[]');
  });
  // 旧版面板写入的 "w:" 记录（整词改）已不再支持，这里忽略
  for (const [k, reading] of Object.entries(saved)) {
    if (!k.startsWith('o:')) continue;
    const occ = k.slice(2);
    const el = document.querySelector(`.cd[data-occ="${occ}"]`);
    const parts = el ? (JSON.parse(el.dataset.parts || '[]').find(x => x.r === reading)?.p || null) : null;
    applyOcc(occ, reading, parts);
  }
}
document.addEventListener('click', e => {
  const cd = e.target.closest('.cd');
  document.querySelectorAll('.menu').forEach(m => m.remove());
  if (!cd) return;
  e.preventDefault();
  const cands = (cd.dataset.cands || '').split('|').filter(Boolean);
  const partsMap = {};
  try { (JSON.parse(cd.dataset.parts || '[]') || []).forEach(x => partsMap[x.r] = x.p); } catch (err) {}
  const menu = document.createElement('div'); menu.className = 'menu';
  if (cands.length < 2) {                       // 无候选：手动输入
    const inp = document.createElement('input');
    inp.className = 'kin'; inp.placeholder = 'ひらがな';
    inp.value = cd.querySelector('rt')?.textContent || '';
    const ok = document.createElement('button');
    ok.textContent = '确定';
    const submit = () => {
      const v = inp.value.trim();
      if (!/^[ぁ-んー]+$/.test(v)) { inp.classList.add('bad'); return; }
      applyOcc(cd.dataset.occ, v, null); menu.remove(); run();
    };
    ok.onclick = ev => { ev.stopPropagation(); submit(); };
    inp.onkeydown = ev => { if (ev.key === 'Enter') submit(); if (ev.key === 'Escape') menu.remove(); };
    menu.append(inp, ok);
    document.body.appendChild(menu);
    const r0 = cd.getBoundingClientRect();
    menu.style.left = Math.max(8, r0.left + scrollX) + 'px';
    menu.style.top = (r0.bottom + scrollY + 4) + 'px';
    inp.focus(); inp.select();
    return;
  }
  for (const c of cands) {
    const b = document.createElement('button');
    b.textContent = c; b.dataset.r = c;
    if (c === (cd.querySelector('rt')?.textContent || '')) b.classList.add('on');
    b.onclick = ev => { ev.stopPropagation(); applyOcc(cd.dataset.occ, c, partsMap[c] || null); menu.remove(); run(); };
    menu.appendChild(b);
  }
  document.body.appendChild(menu);
  const r = cd.getBoundingClientRect();
  menu.style.left = Math.max(8, r.left + scrollX) + 'px';
  menu.style.top = (r.bottom + scrollY + 4) + 'px';
});
async function run(){
  TEXT = document.getElementById('in').value;
  if (!Object.keys(OV).length) OV = load();
  const r = await fetch('/annotate', {method:'POST', headers:{'Content-Type':'application/json'},
                                     body: JSON.stringify({text: TEXT, overrides: OV})});
  const d = await r.json();
  document.getElementById('out').innerHTML = d.lines.map((ln, i) =>
    `<div class="line"><div class="jp">${ln.segments.map(s => segHTML(s, i)).join('')}</div>`
    + `<div class="rm">${esc(d.romaji.lines[i] || '')}</div>`
    + `<div class="ky">${esc(d.keys.lines[i] || '')}</div></div>`).join('');
  markPicked();
}
document.getElementById('go').onclick = run;
run();
</script></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        self._send(200, PAGE.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, b'{"error":"bad json"}', "application/json")
        text = str(req.get("text") or "")
        overrides = req.get("overrides") or {}
        if len(text) > 10000:
            return self._send(413, b'{"error":"too long"}', "application/json")
        with LOCK:
            out = AN.annotate(text, overrides if isinstance(overrides, dict) else None)
        for li, line in enumerate(out["lines"]):          # 服务端渲染注音，前端只插入
            line["html"] = segments_html(line["segments"], candidates=True, occ=li)
        self._send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")


if __name__ == "__main__":
    print("http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
