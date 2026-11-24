/* 演示驱动 3：LRC 编辑、对轴、保存与恢复。只由 --demo3 注入。 */
(async function(){
  'use strict';
  if (window.__MOMO_DEMO3__) return;
  window.__MOMO_DEMO3__ = true;

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (fn, ms=20000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try { if (fn()) return true; } catch (e) {}
      await sleep(80);
    }
    return false;
  };
  const rowEl = i => document.querySelector(`.lerow[data-i="${i}"]`);
  const txInput = (i, trans=false) => rowEl(i)?.querySelector(`input.tx${trans ? '.trans' : ':not(.trans)'}`);
  const menuEl = () => document.querySelector('.menu');

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
    #demo3-panel{position:fixed;right:22px;bottom:22px;z-index:100000;background:#111827ee;
      color:#f4f2ed;border:1px solid #ffffff33;border-radius:12px;padding:12px 14px;
      font:13px/1.45 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      box-shadow:0 12px 40px #0008;max-width:380px}
    #demo3-panel b{display:block;font-size:14px;margin-bottom:3px}
    #demo3-panel small{color:#c9c4b8;display:block;margin:6px 0 9px}
    #demo3-panel button{border:1px solid #ffffff44;background:#f4f2ed;color:#111827;
      border-radius:7px;padding:6px 10px;font:inherit;cursor:pointer}
    #demo3-panel button:disabled{opacity:.4;cursor:default}
    body.demo-running{cursor:none}
    #demo3-caption{position:fixed;left:10px;bottom:70px;width:290px;height:230px;
      z-index:99997;overflow:hidden;pointer-events:none;opacity:0;
      transition:opacity .25s ease;
      -webkit-mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      mask-image:linear-gradient(transparent,#000 18%,#000 82%,transparent);
      font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif}
    #demo3-caption.show{opacity:1}
    #demo3-caption .track{transition:transform .55s cubic-bezier(.2,.7,.2,1)}
    #demo3-caption .capstep{height:58px;min-height:58px;display:flex;align-items:center;gap:8px;
      padding:0 10px;border-radius:8px;opacity:.28;transform:scale(.78);
      transform-origin:left center;transition:opacity .35s ease,transform .35s ease,background .35s ease}
    #demo3-caption .capstep.active{opacity:1;transform:scale(1);background:#101318e8;color:#f4f2ed;
      box-shadow:0 8px 24px #0004}
    #demo3-caption .capstep .n{color:#c8843f;font-size:10px;letter-spacing:.12em;min-width:38px}
    #demo3-caption .capstep .t{color:#5f5a51;font-size:13px;white-space:nowrap}
    #demo3-caption .capstep.active .t{color:#f4f2ed;font-size:15px}
    #demo3-done{position:fixed;left:10px;bottom:310px;width:290px;z-index:99997;
      padding:10px 12px;border:1px solid #ffffff2e;border-radius:9px;
      background:#101318ee;color:#f4f2ed;pointer-events:none;
      font:14px/1.4 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;
      opacity:0;transform:translateY(6px);transition:opacity .25s,transform .25s;
      box-shadow:0 8px 24px #0005}
    #demo3-done.show{opacity:1;transform:none}
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

  const STEPS = ['进入 LRC 编辑','改歌词和翻译','加行 / 删行','拆分 / 合并','波形对轴 1','波形对轴 2','保存','恢复最初'];
  let cap = null, capTrack = null, capRows = [];
  const caption = (text, step) => {
    if (!cap) {
      cap = document.createElement('div');
      cap.id = 'demo3-caption';
      capTrack = document.createElement('div');
      capTrack.className = 'track';
      STEPS.forEach((t, i) => {
        const row = document.createElement('div');
        row.className = 'capstep';
        row.innerHTML = `<span class="n">${String(i + 1).padStart(2,'0')} / ${String(STEPS.length).padStart(2,'0')}</span><span class="t">${t}</span>`;
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
  const stepPause = async (ms=1000) => sleep(ms);
  const endToast = () => {
    let t = document.getElementById('demo3-done');
    if (!t) {
      t = document.createElement('div');
      t.id = 'demo3-done';
      t.textContent = '演示 3 结束';
      document.body.appendChild(t);
    }
    requestAnimationFrame(() => t.classList.add('show'));
  };

  const click = async el => {
    if (!el) throw new Error('demo3: 找不到目标元素');
    el.scrollIntoView({block:'center', behavior:'smooth'});
    await sleep(220);
    move(el);
    await sleep(650);
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

  const clickAt = async (el, x, y) => {
    if (!el) throw new Error('demo3: 找不到波形');
    el.scrollIntoView({block:'center', behavior:'smooth'});
    await sleep(220);
    moveTo(x, y);
    await sleep(650);
    const rip = document.createElement('div');
    rip.className = 'demo-ripple';
    rip.style.left = x + 'px';
    rip.style.top = y + 'px';
    document.body.appendChild(rip);
    setTimeout(() => rip.remove(), 500);
    el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y, button:0}));
    await sleep(500);
  };

  async function typeInput(inp, text) {
    inp.focus();
    inp.select();
    for (const ch of [...text]) {
      if (typeof inp.setRangeText === 'function') {
        inp.setRangeText(ch, inp.selectionStart ?? inp.value.length,
                        inp.selectionEnd ?? inp.value.length, 'end');
      } else {
        inp.value = ch;
      }
      inp.dispatchEvent(new InputEvent('input', {
        bubbles: true, inputType: 'insertText', data: ch,
      }));
      await sleep(90);
    }
    await sleep(180);
  }

  const panel = document.createElement('div');
  panel.id = 'demo3-panel';
  panel.innerHTML = `<b>桃歌 · demo 3</b>
    <small>进入 LRC → 改歌词和翻译 → 加行 / 删行 → 拆分 / 合并 → 波形对轴两处 → 保存 → 恢复最初。</small>
    <button id="demo3-start">开始第三段</button>`;
  document.body.appendChild(panel);

  let running = false;
  const start = async () => {
    if (running) return;
    running = true;
    const b = document.getElementById('demo3-start');
    const panelEl = document.getElementById('demo3-panel');
    if (b) { b.disabled = true; b.textContent = '运行中…'; }
    document.body.classList.add('demo-running');
    if (panelEl) panelEl.style.display = 'none';

    try {
      const norm = s => String(s || '').normalize('NFC');
      const song = NH.LIB.find(x => [x.title, x.orig, x.stem, x.file]
        .some(s => norm(s).includes('たぶん')));
      if (!song) throw new Error('演示 3 需要曲库里有「たぶん」');
      await NH.load(song.uid, false);
      await wait(() => NH.S && String(NH.S.uid) === String(song.uid) && !NH.viewMatching());
      try { NH.au.pause(); } catch (e) {}
      await click(document.getElementById('lrcedit'));
      await wait(() => NH.VIEW_MODE === 'lrc' && NH.EROWS && NH.EROWS.length);
      await sleep(700);
      caption('进入 LRC 编辑', 1);
      await stepPause();

      // 1) 改两行歌词和翻译。
      const rows = [...document.querySelectorAll('.lerow')];
      const targets = rows.filter(el => {
        const i = +el.dataset.i;
        const row = NH.EROWS[i];
        const tx = el.querySelector('input.tx:not(.trans)');
        const ts = el.querySelector('input.ts');
        return row && row.kind === 'lyric'
          && tx && tx.value.trim() && ts && ts.value.trim();
      }).slice(0, 2);
      if (targets.length < 2) throw new Error('演示 3: 可编辑歌词行不足两行');
      for (let k = 0; k < 2; k++) {
        const i = +targets[k].dataset.i;
        const text = txInput(i);
        const trans = txInput(i, true);
        if (!text) throw new Error('演示 3: 找不到歌词输入框');
        await typeInput(text, k === 0 ? 'デモ歌詞一' : 'デモ歌詞二');
        if (trans) await typeInput(trans, k === 0 ? '演示翻译一' : '演示翻译二');
        await sleep(350);
      }
      caption('改两句歌词和翻译', 2);
      await stepPause();

      // 2) 加行，再删掉刚加的行。
      await click(document.getElementById('lrcadd'));
      await sleep(350);
      await click(document.getElementById('lrcdel'));
      await sleep(350);
      caption('加行 / 删行', 3);
      await stepPause();

      // 3) 拆分：把一行从中间拆成两行。
      const splitRow = [...document.querySelectorAll('.lerow')].find(el => {
        const i = +el.dataset.i;
        const tx = el.querySelector('input.tx:not(.trans)');
        return NH.EROWS[i]?.kind === 'lyric'
          && tx && tx.value.trim().length >= 4;
      });
      if (!splitRow) throw new Error('演示 3: 没有可拆分的歌词行');
      const splitIndex = +splitRow.dataset.i;
      const splitInput = txInput(splitIndex);
      splitInput.focus();
      splitInput.setSelectionRange(Math.floor(splitInput.value.length / 2),
                                  Math.floor(splitInput.value.length / 2));
      splitInput.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter', bubbles: true, cancelable: true,
      }));
      await sleep(650);

      // 4) 合并：找一个歌词行，接到上一行；不碰 metadata。
      const mergeIndex = NH.EROWS.findIndex((row, i) =>
        i > 0 && row.kind === 'lyric'
        && NH.EROWS[i - 1].kind !== 'metadata'
        && (row.text || '').trim());
      const mergeInput = mergeIndex >= 0 ? txInput(mergeIndex) : null;
      if (!mergeInput) throw new Error('演示 3: 没有可合并的歌词行');
      mergeInput.focus();
      mergeInput.setSelectionRange(0, 0);
      mergeInput.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Backspace', bubbles: true, cancelable: true,
      }));
      await sleep(650);
      caption('拆分 / 合并', 4);
      await stepPause();

      // 5) 波形点两处并对轴。
      await wait(() => NH.WAVE && document.getElementById('wave'));
      const cv = document.getElementById('wave');
      const bindAt = async (ratio, label, step) => {
        const cr = cv.getBoundingClientRect();
        const x = cr.left + cr.width * ratio;
        const y = cr.top + cr.height / 2;
        await clickAt(cv, x, y);
        await wait(() => NH.MARK !== null);
        let idx = NH.EROWS.findIndex((row, i) =>
          row.kind !== 'metadata' && NH.timeFitsRow(i, NH.MARK));
        if (idx < 0) {
          // 当前窗口内没有合适的行时，选最近的有时间行，按它的时间重新点一次。
          const timed = NH.EROWS.map((row, i) => ({row, i}))
            .filter(x => x.row.kind !== 'metadata'
              && x.row.t !== null && x.row.t !== undefined);
          if (!timed.length) throw new Error('演示 3: 没有可对轴的行');
          const pick = timed[Math.min(timed.length - 1, Math.round(ratio * (timed.length - 1)))];
          const view = NH.DRAWN || {start: 0, span: NH.WAVE.duration || 1};
          const cr2 = cv.getBoundingClientRect();
          const px = cr2.left + Math.max(0, Math.min(1,
            (pick.row.t - view.start) / (view.span || 1))) * cr2.width;
          await clickAt(cv, px, y);
          await wait(() => NH.MARK !== null);
          idx = pick.i;
        }
        const bind = rowEl(idx)?.querySelector('.bind');
        if (!bind) throw new Error('演示 3: 找不到对轴按钮');
        await click(bind);
        await sleep(600);
        caption(label, step);
        await stepPause();
      };
      await bindAt(0.30, '波形对轴 1', 5);
      await bindAt(0.62, '波形对轴 2', 6);

      // 6) 保存。
      await click(document.getElementById('lrcsave'));
      await wait(() => !NH.EDIRTY && !NH.SAVE_PENDING, 10000);
      await sleep(800);
      caption('保存', 7);
      await stepPause();

      // 7) 恢复最初。
      await click(document.getElementById('lrcreset'));
      await wait(() => document.querySelector('.dialog-backdrop'));
      const ok = document.querySelector('.dialog .primary.danger, .dialog .primary');
      if (!ok) throw new Error('演示 3: 恢复确认框没有出现');
      await click(ok);
      await wait(() => !NH.LRC_LOCKED, 10000);
      await sleep(800);
      caption('恢复最初', 8);
      await stepPause();
      endToast();
      if (b) { b.disabled = true; b.textContent = '第三段完成'; }
    } catch (e) {
      const p = document.getElementById('demo3-panel') || document.body.appendChild(document.createElement('div'));
      p.style.display = 'block';
      p.textContent = '演示 3 中断：' + (e && e.message || e);
      document.body.classList.remove('demo-running');
    }
  };
  window.__demoStart = start;
  document.getElementById('demo3-start').onclick = start;
})();
