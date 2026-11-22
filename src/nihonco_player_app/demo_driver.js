/* 演示驱动：只由 --demo 注入，正常页面不会加载。 */
(async function(){
  'use strict';
  if (window.__NIHONCO_DEMO__) return;
  window.__NIHONCO_DEMO__ = true;

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (fn, ms=15000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try { if (fn()) return true; } catch (e) {}
      await sleep(100);
    }
    return false;
  };

  const style = document.createElement('style');
  style.textContent = `
    #demo-cursor{position:fixed;left:0;top:0;width:18px;height:18px;z-index:99999;
      pointer-events:none;transform:translate(-100px,-100px);
      transition:transform .28s cubic-bezier(.2,.7,.2,1);filter:drop-shadow(0 1px 2px #0008)}
    #demo-cursor:before{content:"";position:absolute;left:0;top:0;width:14px;height:14px;
      border:2px solid #fff;border-radius:50%;background:#1f2937}
    #demo-cursor:after{content:"";position:absolute;left:3px;top:3px;width:8px;height:8px;
      border-radius:50%;background:#e9e7e4}
    .demo-ripple{position:fixed;z-index:99998;width:22px;height:22px;border:2px solid #fff;
      border-radius:50%;pointer-events:none;transform:translate(-50%,-50%) scale(.3);
      animation:demo-ripple .45s ease-out forwards}
    @keyframes demo-ripple{to{transform:translate(-50%,-50%) scale(2);opacity:0}}
    #demo-panel{position:fixed;right:22px;bottom:22px;z-index:100000;background:#111827ee;
      color:#f4f2ed;border:1px solid #ffffff33;border-radius:12px;padding:12px 14px;
      font:13px/1.45 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      box-shadow:0 12px 40px #0008;max-width:330px}
    #demo-panel b{display:block;font-size:14px;margin-bottom:3px}
    #demo-panel small{color:#c9c4b8;display:block;margin:6px 0 9px}
    #demo-panel button{border:1px solid #ffffff44;background:#f4f2ed;color:#111827;
      border-radius:7px;padding:6px 10px;font:inherit;cursor:pointer}
    #demo-panel button:disabled{opacity:.4;cursor:default}
    body.demo-running{cursor:none}
  `;
  document.head.appendChild(style);

  const cursor = document.createElement('div');
  cursor.id = 'demo-cursor';
  document.body.appendChild(cursor);
  const move = el => {
    const r = el.getBoundingClientRect();
    cursor.style.transform = `translate(${Math.round(r.left + r.width/2 - 9)}px,${Math.round(r.top + r.height/2 - 9)}px)`;
  };
  const click = async el => {
    if (!el) throw new Error('demo: missing target');
    el.scrollIntoView({block:'center', behavior:'smooth'});
    await sleep(250);
    move(el);
    await sleep(320);
    const r = el.getBoundingClientRect();
    const rip = document.createElement('div');
    rip.className = 'demo-ripple';
    rip.style.left = (r.left + r.width/2) + 'px';
    rip.style.top = (r.top + r.height/2) + 'px';
    document.body.appendChild(rip);
    setTimeout(() => rip.remove(), 500);
    el.click();
    await sleep(280);
  };
  const btn = text => [...document.querySelectorAll('button')].find(b => (b.textContent||'').includes(text));
  const lineEl = i => document.querySelector(`.ln[data-n="${i}"]`);

  const panel = document.createElement('div');
  panel.id = 'demo-panel';
  panel.innerHTML = `<b>nihonco uta · demo</b>
    <small>准备录制后点开始。3 秒后自动操作。<br>录屏开始时不要操作鼠标。</small>
    <button id="demo-prep">准备演示状态</button>
    <button id="demo-start">开始演示</button>`;
  document.body.appendChild(panel);

  let running = false;
  const prepareDemo = async () => {
    if (running) return;
    const prep = document.getElementById('demo-prep');
    try {
      if (prep) { prep.disabled = true; prep.textContent = '准备中…'; }
      const song = NH.LIB.find(x => (x.title||'').includes('たぶん')) || NH.LIB[0];
      await NH.load(song.uid, false);
      await wait(() => NH.S && String(NH.S.uid) === String(song.uid) && !NH.viewMatching());
      const i = NH.LINES.findIndex(l => (l.text||'').includes('そう何'));
      if (i < 0) throw new Error('第 16 行没有找到');
      NH.selectLine(i);
      await sleep(400);
      const ln = lineEl(i);
      const bc = ln && ln.querySelector('.bc[data-base="何"]');
      if (bc) {
        await click(bc);
        await wait(() => document.querySelector('.menu button'));
        const pick = [...document.querySelectorAll('.menu button')].find(b => (b.textContent||'').trim() === 'なに');
        if (pick) await click(pick);
      }
      const correctT = NH.LINES[i].t;
      await click(document.getElementById('lrcedit'));
      await wait(() => NH.VIEW_MODE === 'lrc');
      NH.EROWS[i].t = correctT + 0.5;
      NH.markDirty();
      await NH.saveLrc(true, true);
      await click(document.getElementById('lrcedit'));
      await wait(() => NH.VIEW_MODE === 'normal');
      window.__demoCorrectT = correctT;
      if (prep) { prep.disabled = false; prep.textContent = '已准备'; }
      NH.done('演示状态已准备');
    } catch (e) {
      if (prep) { prep.disabled = false; prep.textContent = '准备失败'; }
      NH.done('准备失败：' + (e && e.message || e));
    }
  };
  window.__nihoncoDemoPrepare = prepareDemo;

  const startDemo = async () => {
    if (running) return;
    running = true;
    const start = document.getElementById('demo-start');
    start.disabled = true;
    start.textContent = '3 秒后开始…';
    document.body.classList.add('demo-running');
    for (const n of ['3','2','1']) { start.textContent = n + ' 秒后开始…'; await sleep(1000); }
    panel.remove();

    try {
      const song = NH.LIB.find(x => (x.title||'').includes('たぶん')) || NH.LIB[0];
      await NH.load(song.uid, false);
      await wait(() => NH.S && String(NH.S.uid) === String(song.uid) && !NH.viewMatching());
      const i = NH.LINES.findIndex(l => (l.text||'').includes('そう何'));
      if (i < 0) throw new Error('demo: 第 16 行没有找到');
      NH.selectLine(i);
      const correctT = window.__demoCorrectT != null ? window.__demoCorrectT : (NH.LINES[i] && NH.LINES[i].t);
      await NH.au.play().catch(() => {});
      await sleep(1500);
      NH.au.pause();
      await sleep(3500);

      // 先暂停在目标句，再开循环；否则 5 秒后已经走到下一句。
      await click(document.getElementById('loop'));
      await NH.au.play().catch(() => {});
      await sleep(8500);
      await click(document.getElementById('loop'));
      await sleep(500);
      NH.au.pause();

      const ln = lineEl(i);
      const bc = ln && ln.querySelector('.bc[data-base="何"]');
      await click(bc);
      await wait(() => document.querySelector('.menu button'));
      const pick = [...document.querySelectorAll('.menu button')].find(b => (b.textContent||'').trim() === 'なん');
      await click(pick);
      await sleep(2000);

      await click(document.getElementById('lrcedit'));
      await wait(() => NH.VIEW_MODE === 'lrc');
      const row = document.querySelector(`.lerow[data-i="${i}"]`);
      await click(row);
      NH.MARK = correctT;
      const bind = row && row.querySelector('.bind');
      await click(bind);
      await click(document.getElementById('lrcsave'));
      await sleep(900);
      await click(document.getElementById('lrcedit'));
      await wait(() => NH.VIEW_MODE === 'normal');
      NH.selectLine(i);
      await NH.au.play().catch(() => {});
      await sleep(6000);
      NH.au.pause();
    } catch (e) {
      const p = document.createElement('div');
      p.id = 'demo-panel';
      p.textContent = '演示中断：' + (e && e.message || e);
      document.body.appendChild(p);
      document.body.classList.remove('demo-running');
    }
  };
  window.__nihoncoDemoStart = startDemo;
  document.getElementById('demo-prep').onclick = prepareDemo;
  document.getElementById('demo-start').onclick = startDemo;
})();
