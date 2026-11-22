/* 演示驱动：只由 --demo 注入。当前只实现第一段。 */
(async function(){
  'use strict';
  if (window.__NIHONCO_DEMO__) return;
  window.__NIHONCO_DEMO__ = true;

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
  const button = text => [...document.querySelectorAll('button')]
    .find(b => (b.textContent || '').includes(text));

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
    #demo-caption{position:fixed;left:10px;bottom:70px;width:250px;height:230px;
      z-index:99997;overflow:hidden;pointer-events:none;opacity:0;
      transition:opacity .25s ease;
      -webkit-mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif}
    #demo-caption.show{opacity:1}
    #demo-caption .track{transition:transform .55s cubic-bezier(.2,.7,.2,1)}
    #demo-caption .capstep{height:58px;min-height:58px;display:flex;align-items:center;gap:8px;
      padding:0 10px;border-radius:8px;opacity:.28;transform:scale(.78);
      transform-origin:left center;transition:opacity .35s ease,transform .35s ease,background .35s ease}
    #demo-caption .capstep.active{opacity:1;transform:scale(1);background:#101318e8;color:#f4f2ed;
      box-shadow:0 8px 24px #0004}
    #demo-caption .capstep .n{color:#c8843f;font-size:10px;letter-spacing:.12em;min-width:38px}
    #demo-caption .capstep .t{color:#5f5a51;font-size:13px;white-space:nowrap}
    #demo-caption .capstep.active .t{color:#f4f2ed;font-size:15px}
    #demo-done{position:fixed;left:10px;bottom:310px;width:250px;z-index:99997;
      padding:10px 12px;border:1px solid #ffffff2e;border-radius:9px;
      background:#101318ee;color:#f4f2ed;pointer-events:none;
      font:14px/1.4 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      opacity:0;transform:translateY(6px);transition:opacity .25s,transform .25s;
      box-shadow:0 8px 24px #0005}
    #demo-done.show{opacity:1;transform:none}
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
  const STEPS = ['歌词页','罗马音','跳转','单句循环：开','单句循环：关','上一句','下一句'];
  let cap = null;
  let capTrack = null;
  let capRows = [];
  const caption = (text, step) => {
    if (!cap) {
      cap = document.createElement('div');
      cap.id = 'demo-caption';
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
    let t = document.getElementById('demo-done');
    if (!t) {
      t = document.createElement('div');
      t.id = 'demo-done';
      t.textContent = '演示结束';
      document.body.appendChild(t);
    }
    requestAnimationFrame(() => t.classList.add('show'));
  };

  const click = async el => {
    if (!el) throw new Error('demo: 找不到目标元素');
    el.scrollIntoView({block:'center', behavior:'smooth'});
    await sleep(250);
    move(el);
    await sleep(1000);  // 在目标上停留 1 秒再点击
    const r = el.getBoundingClientRect();
    const rip = document.createElement('div');
    rip.className = 'demo-ripple';
    rip.style.left = (r.left + r.width/2) + 'px';
    rip.style.top = (r.top + r.height/2) + 'px';
    document.body.appendChild(rip);
    setTimeout(() => rip.remove(), 500);
    el.click();
    await sleep(250);
    // 点完按钮后把光标挪到按钮上方/下方，避免压住按钮或滑到相邻按钮。
    const sideX = r.left + r.width / 2;
    const sideY = (r.top > innerHeight * 0.58)
      ? Math.max(14, r.top - 24)
      : Math.min(innerHeight - 14, r.bottom + 24);
    moveTo(sideX, sideY);
    await sleep(120);
  };

  const panel = document.createElement('div');
  panel.id = 'demo-panel';
  panel.innerHTML = `<b>nihonco uta · demo 1</b>
    <small>从头播放 → 第 2 句后 6 秒 → 跳第 15 行 → 播到第 17 行 → 循环一次 → 关循环 8 秒 → 上一句 7 秒 → 下一句 7.5 秒 → 暂停。</small>
    <button id="demo-start">开始第一段</button>`;
  document.body.appendChild(panel);

  let running = false;
  const start = async () => {
    if (running) return;
    running = true;
    const b = document.getElementById('demo-start');
    const panelEl = document.getElementById('demo-panel');
    if (b) { b.disabled = true; b.textContent = '运行中…'; }
    document.body.classList.add('demo-running');
    if (panelEl) panelEl.style.display = 'none';
    try {
      const song = NH.LIB.find(x => (x.title || '').includes('たぶん')) || NH.LIB[0];
      await NH.load(song.uid, false);
      await wait(() => NH.S && String(NH.S.uid) === String(song.uid) && !NH.viewMatching());
      NH.au.currentTime = 0;
      await sleep(1000);  // 播放前停顿 1 秒
      await NH.au.play().catch(() => {});
      caption('歌词页', 1);

      // 播放开头：光标先停在左侧歌词栏，3 秒后移到右侧罗马音栏。
      const lyricPane = document.getElementById('lyr');
      const romajiPane = document.getElementById('rmcol');
      if (lyricPane) {
        const lr = lyricPane.getBoundingClientRect();
        moveTo(lr.right - 18, lr.top + 70);
      }
      await sleep(3000);
      caption('罗马音', 2);
      if (romajiPane) {
        const rr = romajiPane.getBoundingClientRect();
        moveTo(rr.right - 18, rr.top + 70);
      }

      // 第一句放完、第二句播放途中：用 NAV 的第二个实际歌词行判断。
      await wait(() => {
        const a = NH.NAV || [];
        if (a.length < 2) return false;
        return NH.idxAt(NH.au.currentTime) >= a[1];
      }, 20000);
      await sleep(6000);  // 第二句进入播放途中，再留 6 秒

      // 跳到第 15 行；继续播放。
      await click(lineEl(14));
      caption('跳转', 3);
      await wait(() => NH.idxAt(NH.au.currentTime) >= 14, 10000);

      // 播放到第 17 行的途中。
      await wait(() => NH.idxAt(NH.au.currentTime) >= 16, 10000);

      // 确保单句循环是关，然后开启。
      const loop = document.getElementById('loop');
      if (!loop) throw new Error('找不到单句循环');
      if (loop.textContent.includes('开')) await click(loop);
      await click(loop);
      caption('单句循环：开', 4);

      // 等到第 17 行确实循环一次：先看到它走过起点，再看到时间回卷。
      const row17 = NH.LINES[16];
      const start17 = row17 && row17.t;
      let passed = false;
      await wait(() => {
        if (!NH.loop || NH.LOOP_ROW !== 16 || start17 == null) return false;
        const t = NH.au.currentTime;
        if (t > start17 + 1.0) passed = true;
        return passed && t < start17 + 0.7;
      }, 12000);

      // 第 17 行循环一次后：关闭循环，等 8 秒再点上一句。
      await click(loop);
      caption('单句循环：关', 5);
      await sleep(8000);
      await click(document.getElementById('prev'));
      caption('上一句', 6);
      await sleep(7000);
      await click(document.getElementById('next'));
      caption('下一句', 7);
      await sleep(7500);
      NH.au.pause();
      endToast();

      if (b) { b.disabled = true; b.textContent = '第一段完成'; }
    } catch (e) {
      const p = document.getElementById('demo-panel') || document.body.appendChild(document.createElement('div'));
      p.textContent = '演示中断：' + (e && e.message || e);
      document.body.classList.remove('demo-running');
    }
  };
  window.__demoStart = start;
  document.getElementById('demo-start').onclick = start;
})();
