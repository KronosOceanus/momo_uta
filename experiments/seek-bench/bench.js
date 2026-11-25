'use strict';

const TARGETS = [1.03, 4.27, 7.51];
const SPEEDS = [1.0, 0.8, 0.65];
const REPS = 3;
const CLICK = 0.5;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const median = xs => {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const p95 = xs => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil(s.length * 0.95) - 1)];
};
const fmt = x => `${x >= 0 ? '+' : ''}${(x * 1000).toFixed(2)}ms`;

let ctx = null;
let buffer = null;

async function init() {
  if (ctx) return;
  ctx = new AudioContext({sampleRate: 44100});
  await ctx.resume();
  const res = await fetch('click.wav');
  if (!res.ok) throw new Error('缺少 click.wav，请先运行 generate_click.py');
  buffer = await ctx.decodeAudioData(await res.arrayBuffer());
}

async function measure(speed, target) {
  const when = ctx.currentTime + 0.25;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.playbackRate.value = speed;
  const proc = ctx.createScriptProcessor(256, 1, 1);
  const silent = ctx.createGain();
  silent.gain.value = 0;
  const blocks = [];
  proc.onaudioprocess = e => {
    blocks.push({time: e.playbackTime, data: e.inputBuffer.getChannelData(0).slice()});
  };
  source.connect(proc);
  proc.connect(silent);
  silent.connect(ctx.destination);
  source.connect(ctx.destination); // 可听；方便确认测试真的在出声
  source.start(when, target);
  await sleep(1400);
  source.stop();
  source.disconnect();
  proc.disconnect();
  silent.disconnect();
  proc.onaudioprocess = null;

  const expectedClick = Math.ceil((target + 1e-9) / CLICK) * CLICK;
  let actual = null;
  for (const b of blocks) {
    for (let i = 0; i < b.data.length; i++) {
      if (Math.abs(b.data[i]) < 0.2) continue;
      const t = b.time + i / ctx.sampleRate;
      if (t < when - 0.01) continue;
      actual = target + (t - when) * speed;
      break;
    }
    if (actual !== null) break;
  }
  if (actual === null) throw new Error(`没有捕捉到 click（${speed}× @ ${target}s）`);
  return {
    speed, target, expectedClick, actual,
    error: actual - expectedClick,
    onset: actual === null ? null : (actual - target) / speed,
  };
}

document.getElementById('run').addEventListener('click', async () => {
  const btn = document.getElementById('run');
  const status = document.getElementById('status');
  const rows = document.getElementById('rows');
  const summary = document.getElementById('summary');
  btn.disabled = true;
  rows.innerHTML = '';
  summary.textContent = '';
  try {
    await init();
    const all = [];
    for (const speed of SPEEDS) {
      for (const target of TARGETS) {
        for (let r = 0; r < REPS; r++) {
          const m = await measure(speed, target);
          all.push(m);
          rows.insertAdjacentHTML('beforeend',
            `<tr><td>${speed.toFixed(2)}×</td><td>${target.toFixed(2)}s</td>` +
            `<td>${m.expectedClick.toFixed(3)}s</td><td>${m.actual.toFixed(3)}s</td>` +
            `<td>${fmt(m.error)}</td><td>${(m.onset * 1000).toFixed(1)}ms</td></tr>`);
          await sleep(80);
        }
      }
    }
    const groups = [];
    for (const speed of SPEEDS) {
      const errs = all.filter(x => x.speed === speed).map(x => Math.abs(x.error));
      groups.push(`${speed.toFixed(2)}×  |error| median=${(median(errs) * 1000).toFixed(2)}ms p95=${(p95(errs) * 1000).toFixed(2)}ms max=${(Math.max(...errs) * 1000).toFixed(2)}ms`);
    }
    summary.textContent = groups.join('\n');
    status.textContent = '完成';
  } catch (e) {
    status.textContent = '失败';
    summary.textContent = String(e && e.stack || e);
  } finally {
    btn.disabled = false;
  }
});
