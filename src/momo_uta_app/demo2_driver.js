/* 演示驱动 2：注音修改与全部重置。只由 --demo2 注入。 */
(async function(){
  'use strict';
  if (window.__MOMO_DEMO2__) return;
  window.__MOMO_DEMO2__ = true;

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (fn, ms=20000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try { if (fn()) return true; } catch (e) {}
      await sleep(80);
    }
    return false;
  };
  const lineEl = i => document.querySelector(`.ln[data-n="${i}"]`);
  const menuEl = () => document.querySelector('.menu');
  const read = el => (el.querySelector('rt')?.textContent || '').trim();

  const style = document.createElement('style');
  style.textContent = `
    #demo-cursor{position:fixed;left:0;top:0;width:18px;height:18px;z-index:99999;
      pointer-events:none;transform:translate(-100px,-100px);
      transition:transform .28s cubic-bezier(.2,.7,.2,1);
      filter:drop-shadow(0 1px 2px #0008)}
    #demo-cursor:before{content:"";position:absolute;left:0;top:0;width:14px;height:14px;
      border:2px solid #fff;border-radius:50%;background:#1f2937}
    #demo-cursor:after{content:"";position:absolute;left:3px;top:3px;width:8px;height:8px;
      border-radius:50%;background:#e9e7e4}
    .demo-ripple{position:fixed;z-index:99998;width:22px;height:22px;border:2px solid #fff;
      border-radius:50%;pointer-events:none;transform:translate(-50%,-50%) scale(.3);
      animation:demo-ripple .45s ease-out forwards}
    @keyframes demo-ripple{to{transform:translate(-50%,-50%) scale(2);opacity:0}}
    #demo2-panel{position:fixed;right:22px;bottom:22px;z-index:100000;background:#111827ee;
      color:#f4f2ed;border:1px solid #ffffff33;border-radius:12px;padding:12px 14px;
      font:13px/1.45 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      box-shadow:0 12px 40px #0008;max-width:360px}
    #demo2-panel b{display:block;font-size:14px;margin-bottom:3px}
    #demo2-panel small{color:#c9c4b8;display:block;margin:6px 0 9px}
    #demo2-panel button{border:1px solid #ffffff44;background:#f4f2ed;color:#111827;
      border-radius:7px;padding:6px 10px;font:inherit;cursor:pointer}
    #demo2-panel button:disabled{opacity:.4;cursor:default}
    body.demo-running{cursor:none}
    #demo2-caption{position:fixed;left:10px;bottom:70px;width:270px;height:230px;
      z-index:99997;overflow:hidden;pointer-events:none;opacity:0;
      transition:opacity .25s ease;
      -webkit-mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif}
    #demo2-caption.show{opacity:1}
    #demo2-caption .track{transition:transform .55s cubic-bezier(.2,.7,.2,1)}
    #demo2-caption .capstep{height:58px;min-height:58px;display:flex;align-items:center;gap:8px;
      padding:0 10px;border-radius:8px;opacity:.28;transform:scale(.78);
      transform-origin:left center;transition:opacity .35s ease,transform .35s ease,background .35s ease}
    #demo2-caption .capstep.active{opacity:1;transform:scale(1);background:#101318e8;color:#f4f2ed;
      box-shadow:0 8px 24px #0004}
    #demo2-caption .capstep .n{color:#c8843f;font-size:10px;letter-spacing:.12em;min-width:38px}
    #demo2-caption .capstep .t{color:#5f5a51;font-size:13px;white-space:nowrap}
    #demo2-caption .capstep.active .t{color:#f4f2ed;font-size:15px}
    #demo2-done{position:fixed;left:10px;bottom:310px;width:270px;z-index:99997;
      padding:10px 12px;border:1px solid #ffffff2e;border-radius:9px;
      background:#101318ee;color:#f4f2ed;pointer-events:none;
      font:14px/1.4 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      opacity:0;transform:translateY(6px);transition:opacity .25s,transform .25s;
      box-shadow:0 8px 24px #0005}
    #demo2-done.show{opacity:1;transform:none}
  `;
  document.head.appendChild(style);

  const cursor = document.createElement('div');
  cursor.id = 'demo-cursor';
  document.body.appendChild(cursor);
  const moveTo = (x, y) => {
    cursor.style.transform = `translate(${Math.round(x - 9)}px,${Math.round(y - 9)}px)`;
  };
  const move = el => {
    const r = el.getBoundingClientRect();
    moveTo(r.left + r.width/2, r.top + r.height/2);
  };

  const STEPS = ['打开歌曲','改两个 B','打开振假名编辑','改两个 A','改两个 B','全部重置','回看六处'];
  let cap = null, capTrack = null, capRows = [];
  const caption = (text, step) => {
    if (!cap) {
      cap = document.createElement('div');
      cap.id = 'demo2-caption';
      capTrack = document.createElement('div');
      capTrack.className = 'track';
      STEPS.forEach((t, i) => {
        const row = document.createElement('div');
        row.className = 'capstep';
        row.innerHTML = `<span class="n">${String(i + 1).padStart(2,'0')} / 07</span><span class="t">${t}</span>`;
        capTrack.appendChild(row);
        capRows.push(row);
      });
      cap.appendChild(capTrack);
      document.body.appendChild(cap);
    }
    const i = Math.max(0, Math.min(STEPS.length - 1, (step || 1) - 1));
    capRows.forEach((row, k) => {
      row.classList.toggle('active', k === i);
      if (k === i && text) row.querySelector('.t').textContent = text;
    });
    capTrack.style.transform = `translateY(${-(i * 58 - (230 - 58) / 2)}px)`;
    requestAnimationFrame(() => cap.classList.add('show'));
  };

  const endToast = () => {
    let t = document.getElementById('demo2-done');
    if (!t) {
      t = document.createElement('div');
      t.id = 'demo2-done';
      t.textContent = '演示 2 结束';
      document.body.appendChild(t);
    }
    requestAnimationFrame(() => t.classList.add('show'));
  };

  const click = async el => {
    if (!el) throw new Error('demo2: 找不到目标元素');
    el.scrollIntoView({block:'center', behavior:'smooth'});
    await sleep(250);
    move(el);
    await sleep(700);
    const r = el.getBoundingClientRect();
    const rip = document.createElement('div');
    rip.className = 'demo-ripple';
    rip.style.left = (r.left + r.width/2) + 'px';
    rip.style.top = (r.top + r.height/2) + 'px';
    document.body.appendChild(rip);
    setTimeout(() => rip.remove(), 500);
    el.click();
    await sleep(220);
    const sideY = (r.top > innerHeight * 0.58)
      ? Math.max(14, r.top - 24)
      : Math.min(innerHeight - 14, r.bottom + 24);
    moveTo(r.left + r.width / 2, sideY);
    await sleep(100);
  };

  const panel = document.createElement('div');
  panel.id = 'demo2-panel';
  panel.innerHTML = `<b>桃歌 · demo 2</b>
    <small>打开「たぶん」→ 改两个 B → 打开振假名编辑 → 改两个 A 和两个 B → 全部重置 → 回看六处。</small>
    <button id="demo2-start">开始第二段</button>`;
  document.body.appendChild(panel);

  const candidates = el => (el.dataset.cands || '').split('|').filter(Boolean);
  const keyOf = (li, start) => `${li}:${start}`;
  const touched = [];
  const seen = (li, start) => touched.some(t => keyOf(t.li, t.start) === keyOf(li, start));
  const bEls = () => [...document.querySelectorAll('.ln .bc')]
    .filter(el => el.querySelector('ruby.rb') && candidates(el).length >= 2);
  const aEls = () => [...document.querySelectorAll('.ln .ew')]
    .filter(el => el.querySelector('ruby.ra'));
  const bEditable = () => [...document.querySelectorAll('.ln .bc, .ln .ew')]
    .filter(el => el.querySelector('ruby.rb'));
  const wrong = cur => cur === 'ぴ' ? 'ぷ' : 'ぴ';

  async function editWithInput(el, value) {
    await click(el);
    await wait(() => menuEl() && menuEl().querySelector('.kin'));
    const inp = menuEl()?.querySelector('.kin');
    if (!inp) throw new Error('demo2: 读音输入框没有打开');
    inp.value = value;
    inp.dispatchEvent(new Event('input', {bubbles:true}));
    inp.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
    await sleep(850);
  }

  let running = false;
  const start = async () => {
    if (running) return;
    running = true;
    const b = document.getElementById('demo2-start');
    const panelEl = document.getElementById('demo2-panel');
    if (b) { b.disabled = true; b.textContent = '运行中…'; }
    document.body.classList.add('demo-running');
    if (panelEl) panelEl.style.display = 'none';

    try {
      const norm = s => String(s || '').normalize('NFC');
      const song = NH.LIB.find(x => [x.title, x.orig, x.stem, x.file]
        .some(s => norm(s).includes('たぶん')));
      if (!song) throw new Error('演示 2 需要曲库里有「たぶん」');
      await NH.load(song.uid, false);
      await wait(() => NH.S && String(NH.S.uid) === String(song.uid) && !NH.viewMatching());
      try { NH.au.pause(); } catch (e) {}
      caption('打开歌曲：たぶん（不播放）', 1);
      await sleep(900);

      // 1) 正常模式下改两个 B：从候选里选一个不同读音。
      for (let i = 0; i < 2; i++) {
        const el = bEls().find(x => !seen(+x.closest('.ln').dataset.n, x.dataset.start));
        if (!el) throw new Error('演示 2: B 档位不足两个');
        const li = +el.closest('.ln').dataset.n;
        const start = el.dataset.start;
        const cur = read(el);
        const alt = candidates(el).find(c => c !== cur);
        if (!alt) throw new Error('演示 2: B 没有其他候选');
        await click(el);
        await wait(() => menuEl());
        const btn = [...(menuEl()?.querySelectorAll('button') || [])]
          .find(x => x.textContent.trim() === alt);
        if (!btn) throw new Error('演示 2: 找不到 B 候选按钮');
        await click(btn);
        await sleep(850);
        touched.push({li, start, kind:'B'});
        caption(`改 B 档位 ${i + 1}：${cur} → ${alt}`, 2);
      }

      // 2) 打开右上角振假名编辑模式。
      await click(document.getElementById('edit'));
      await wait(() => NH.VIEW_MODE === 'kana');
      caption('打开振假名编辑模式', 3);
      await sleep(700);

      // 3) 编辑模式下手动改两个 A。
      for (let i = 0; i < 2; i++) {
        const el = aEls().find(x => !seen(+x.closest('.ln').dataset.n, x.dataset.start));
        if (!el) throw new Error('演示 2: A 档位不足两个');
        const li = +el.closest('.ln').dataset.n;
        const start = el.dataset.start;
        const cur = read(el);
        const value = wrong(cur);
        await editWithInput(el, value);
        touched.push({li, start, kind:'A'});
        caption(`改 A 档位 ${i + 1}：${cur} → ${value}`, 4);
      }

      // 4) 编辑模式下再改两个 B（避开刚改过的两个）。
      for (let i = 0; i < 2; i++) {
        const el = bEditable().find(x => !seen(+x.closest('.ln').dataset.n, x.dataset.start));
        if (!el) throw new Error('演示 2: 可编辑 B 档位不足两个');
        const li = +el.closest('.ln').dataset.n;
        const start = el.dataset.start;
        const cur = read(el);
        const value = wrong(cur);
        await editWithInput(el, value);
        touched.push({li, start, kind:'B'});
        caption(`改 B 档位 ${i + 3}：${cur} → ${value}`, 5);
      }

      // 5) 全部重置并确认。
      const reset = document.getElementById('resetall');
      if (!reset) throw new Error('演示 2: 找不到全部重置');
      await click(reset);
      await wait(() => document.querySelector('.dialog-backdrop'));
      const ok = document.querySelector('.dialog .primary.danger, .dialog .primary');
      if (!ok) throw new Error('演示 2: 重置确认框没有出现');
      await click(ok);
      caption('全部重置：确认', 6);
      await sleep(1000);
      await wait(() => NH.S && !NH.viewMatching());
      await sleep(700);

      // 6) 重置后逐个悬停刚才改过的六处注音。
      caption('回看六处注音', 7);
      for (const t of touched) {
        const line = lineEl(t.li);
        let el = null;
        if (line) {
          el = [...line.querySelectorAll('[data-start]')]
            .find(x => x.dataset.start === String(t.start));
        }
        if (el) {
          move(el);
          await sleep(700);
        }
      }
      endToast();
      if (b) { b.disabled = true; b.textContent = '第二段完成'; }
    } catch (e) {
      const p = document.getElementById('demo2-panel') || document.body.appendChild(document.createElement('div'));
      p.style.display = 'block';
      p.textContent = '演示 2 中断：' + (e && e.message || e);
      document.body.classList.remove('demo-running');
    }
  };
  window.__demoStart = start;
  document.getElementById('demo2-start').onclick = start;
})();
