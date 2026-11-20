/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
// 播放器 · 界面与逻辑总入口（按加载顺序共享全局作用域）
// 文件划分（player.html 里按顺序加载）：
//   10-app.js     状态、工具、歌单、载入单曲、右侧面板
//   20-editor.js  LRC 编辑表格（对齐、增删、粘贴、保存）
//   30-playback.js 统一时间语义、自绘播放条、波形跟随、键盘
NH.S = null; NH.LINES = []; NH.NAV = []; NH.CUR = -1; NH.loop = false; NH.ids = []; NH.MODE = 'rm'; NH.PLAYING = null; NH.EDITMODE = false;
const lyr=document.getElementById('lyr');
NH.LIB = []; NH.PLS = []; NH.DRAG = null;
NH.SELU = new Set(); NH.SEL_LIST = null; NH.SEL_ANCHOR = null;

// ── 波形与整体偏移 ────────────────────────────────
const CFG=(window.__CFG)||{};
const UI=(CFG.player&&CFG.player.ui)||{};
const VC=(CFG.vocals)||{};
NH.WAVE = null; NH.VIEW = {span:UI.wave_span||5}; NH.OFFSET = 0; NH.FOLLOW = UI.follow_default!==false; NH.DRAWN = null;
const cv=document.getElementById('wave'), cx=cv.getContext('2d');
if(cv.style) cv.style.height=(UI.wave_height||120)+'px';
const SPAN_MIN=UI.wave_span_min||2, SPAN_MAX=UI.wave_span_max||10;   // 秒

NH.PAN_START = 0;
function clampStart(st, span){
  const dur=(NH.WAVE && NH.WAVE.duration) || 0;
  return Math.max(0, Math.min(Math.max(0, dur-span), st));
}
function viewStart(){
  const dur=(NH.WAVE && NH.WAVE.duration) || 0;
  const span=Math.min(NH.VIEW.span, dur||NH.VIEW.span);
  if(!NH.FOLLOW) return {start:clampStart(NH.PAN_START, span), span};
  let s0=(NH.au.currentTime||0) - span/2;
  s0=Math.max(0, Math.min((dur||0)-span, s0));
  return {start:s0, span};
}

// ── 缩放 / 跳转 / 数值输入 ──────────────────────
const SPAN_LO=SPAN_MIN, SPAN_HI=SPAN_MAX;
function spanText(v){ return (Math.round(v*10)/10).toString().replace(/\.0$/,'')+'s'; }
function updateWaveHint(){
  const h=document.getElementById('wavehint');
  if(!h) return;
  const src = NH.WAVE && NH.WAVE.source==='vocals' ? '人声波形' : '原曲波形';
  h.textContent = NH.WAVE ? `${src} ${fmt(NH.WAVE.duration)} · 窗口 ${spanText(NH.VIEW.span)}` : '';
}
function syncWaveLabels(){
  const z=document.getElementById('zoomval'); if(z) z.textContent=spanText(NH.VIEW.span);
  const b=document.getElementById('jumpback'), f=document.getElementById('jumpfwd');
  if(b) b.textContent='◀ '+spanText(NH.VIEW.span);
  if(f) f.textContent=spanText(NH.VIEW.span)+' ▶';
  updateWaveHint();
}
function syncFollow(){
  const b=document.getElementById('wavefollow');
  if(!b) return;
  b.textContent='跟随：'+(NH.FOLLOW?'开':'关');
  b.classList.toggle('on', NH.FOLLOW);
}
function setWaveSpan(v){
  NH.VIEW.span=Math.max(SPAN_LO, Math.min(SPAN_HI, +v||NH.VIEW.span));
  if(!NH.FOLLOW) NH.PAN_START=clampStart(NH.PAN_START, NH.VIEW.span);
  syncWaveLabels();
  if(typeof drawWave==='function') drawWave();
}
function inlineEdit(el, cur, opts){
  if(!el || el.querySelector('input')) return;
  const old=el.textContent;
  const inp=document.createElement('input');
  inp.className='numin'; inp.value=opts.fmt(cur);
  el.textContent=''; el.appendChild(inp); inp.focus(); inp.select();
  let closed=false;
  const close=commit=>{
    if(closed) return; closed=true;
    const v=parseFloat(inp.value);
    el.textContent=old;
    if(commit && isFinite(v)) opts.apply(Math.max(opts.min, Math.min(opts.max, v)));
  };
  inp.addEventListener('keydown',e=>{
    e.stopPropagation();
    if(e.key==='Enter'){ e.preventDefault(); close(true); }
    else if(e.key==='Escape'){ close(false); }
  });
  inp.addEventListener('blur',()=>close(false));
}
NH.CANVAS_W = 0; NH.CANVAS_H = 0; NH.CV_W = 0;
function measureCanvas(){ NH.CV_W=cv.getBoundingClientRect().width; }
function fitCanvas(){
  // 用缓存宽度：避免每帧 getBoundingClientRect 触发同步布局（换行时最容易卡一下）
  if(!NH.CV_W) measureCanvas();
  const dpr=1;                                            // 波形是细线，1x 足够，合成压力最小
  const w=Math.max(1,Math.round(NH.CV_W*dpr)), h=Math.max(1,Math.round((UI.wave_height||120)*dpr));
  if(w!==NH.CANVAS_W || h!==NH.CANVAS_H){
    cv.width=w; cv.height=h; NH.CANVAS_W=w; NH.CANVAS_H=h;
    cx.setTransform(dpr,0,0,dpr,0,0);
  }
  return NH.CV_W;
}
function drawWave(){
  const h=UI.wave_height||120;
  const w=fitCanvas();
  cx.clearRect(0,0,w,h);                 // 透明底：少写一层全画布填充
  if(!NH.WAVE || !NH.WAVE.peaks){ return; }
  const {start, span}=viewStart();
  NH.DRAWN={start, span};
  const {step, peaks}=NH.WAVE;
  const perPx=span/w, mid=h/2;
  const i0=Math.max(0,Math.floor(start/step)), i1=Math.min(peaks.length, Math.ceil((start+span)/step));
  cx.strokeStyle='#4a7f6b'; cx.beginPath();
  for(let i=i0;i<i1;i++){
    const x=Math.round((i*step-start)/perPx);
    const [mn,mx]=peaks[i];
    cx.moveTo(x+0.5, mid-mx*mid*0.95);
    cx.lineTo(x+0.5, mid-mn*mid*0.95);
  }
  cx.stroke();
  // 只要"每一句开头的线"，其他辅助线一律不画
  {
    const ls = NH.LRCEDIT ? NH.EROWS : NH.LINES;
    cx.strokeStyle='rgba(200,132,63,0.62)';   // 暖橙色，和绿色波形、亮绿播放头区分开
    cx.lineWidth=1; cx.beginPath();
    (ls||[]).forEach(l=>{
      if(!l || l.t==null) return;
      const lt=l.t+NH.OFFSET;
      if(lt<start || lt>start+span) return;
      const lx=Math.round((lt-start)/perPx)+0.5;
      cx.moveTo(lx,0); cx.lineTo(lx,h);
    });
    cx.stroke();
  }
  // 播放头居中
  const x=Math.round(((NH.au.currentTime||0)-start)/perPx);
  cx.strokeStyle='#7fbfa6'; cx.beginPath(); cx.moveTo(x+0.5,0); cx.lineTo(x+0.5,h); cx.stroke();
}
function fmt(t){ const m=Math.floor(t/60), s=Math.round(t%60); return `${m}:${String(s).padStart(2,'0')}`; }

NH.VSTAT = null; NH.VPOLL = 0;
function paintVStatus(){
  const el=document.getElementById('vchip'); if(!el) return;
  if(!NH.VSTAT || NH.VSTAT.state==='none'){ el.hidden=true; return; }
  el.hidden=false;
  if(NH.VSTAT.state==='done'){
    el.textContent = NH.VSTAT.has_vocals ? '有人声' : '纯音乐';
    el.classList.toggle('vdone', true);
    el.classList.toggle('vinst', !NH.VSTAT.has_vocals);
  }else if(NH.VSTAT.state==='failed'){
    el.textContent='人声分离失败';
  }else{
    el.textContent = NH.VSTAT.state==='queued' ? '人声分离：排队' : '人声分离中…';
  }
}
async function ensureVocals(idx){
  try{ await api('/api/vocals',{action:'ensure', idx}); }catch(e){ return null; }
  return pollVocals(idx);
}
async function pollVocals(idx){
  const seq=++NH.VPOLL;
  for(let k=0;k<400;k++){
    if(seq!==NH.VPOLL || !NH.S || String(NH.S.idx)!==String(idx)) return null;
    let st=null;
    try{ st=await api('/api/vocals/'+idx); }catch(e){ return null; }
    NH.VSTAT=st; paintVStatus();
    if(st.state==='done'){
      if(NH.LRCEDIT) loadWave(true);          // 分离完成 → 换成人声波形
      return st;
    }
    if(st.state==='failed') return st;
    await new Promise(r=>setTimeout(r,1500));
  }
  return null;
}

async function loadWave(force){
  if(!NH.S) return;
  if(!force && NH.WAVE) return;
  NH.WAVE=null;
  try{
    const src=(NH.VSTAT && NH.VSTAT.state==='done' && NH.VSTAT.has_vocals) ? '?src=vocals' : '';
    const d=await api('/api/wave/'+NH.S.idx+src);
    if(d.error){ document.getElementById('wavehint').textContent='无法生成波形：'+d.error; return; }
    NH.WAVE=d;
    updateWaveHint();
    drawWave();
  }catch(e){ document.getElementById('wavehint').textContent='波形加载失败'; }
}
(function waveLoop(){
  let last=0;
  function tick(ts){
    if(NH.WAVE && NH.LRCEDIT && !NH.au.paused && ts-last>=32){ drawWave(); last=ts; }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
document.getElementById('wavefollow').onclick=e=>{
  NH.FOLLOW=!NH.FOLLOW;
  e.target.textContent='跟随：'+(NH.FOLLOW?'开':'关');
  e.target.classList.toggle('on', NH.FOLLOW);
  if(!NH.FOLLOW){ NH.DRAWN=NH.DRAWN||viewStart(); }   // 关掉时冻结当前窗口
};
cv.addEventListener('contextmenu', e=>e.preventDefault());
// 双指滑动（触控板）/ 滚轮：左右平移窗口（竖向滑动也当横向用）
cv.addEventListener('wheel', e=>{
  if(!NH.WAVE) return;
  e.preventDefault();
  const d=e.deltaX || e.deltaY;
  if(!d) return;
  const v=viewStart(), w=cv.getBoundingClientRect().width || 1;
  if(NH.FOLLOW){ NH.FOLLOW=false; syncFollow(); }      // 手动平移 → 关闭跟随
  NH.PAN_START=clampStart(v.start + d*v.span/w, v.span);
  drawWave();
}, {passive:false});
cv.addEventListener('click', e=>{
  if(!NH.WAVE || e.button===2) return;
  const r=cv.getBoundingClientRect();
  const ratio=Math.max(0, Math.min(1,(e.clientX-r.left)/r.width));
  const v=NH.DRAWN || viewStart();                 // 所见即所得
  const t=Math.round((v.start + ratio*v.span)*100)/100;
  NH.seekPrecise(t);
  NH.MARK=Math.round(t*100)/100;
  drawWave();
  const el=document.getElementById('mark');
  el.textContent='标记：'+NH.lrcFmt(NH.MARK); el.classList.add('set');
  drawWave();
});
window.addEventListener('resize', ()=>{ measureCanvas(); drawWave(); });

document.getElementById('zoomout').onclick=()=>setWaveSpan(NH.VIEW.span-1);
document.getElementById('zoomin').onclick=()=>setWaveSpan(NH.VIEW.span+1);
document.getElementById('zoomval').onclick=()=>{
  inlineEdit(document.getElementById('zoomval'), NH.VIEW.span,
    {min:SPAN_LO, max:SPAN_HI, fmt:v=>String(v), apply:v=>setWaveSpan(v)});
};
document.querySelectorAll('#wavebar [data-seek]').forEach(b=>b.onclick=()=>{
  NH.seekPrecise(Math.max(0, Math.min(NH.au.duration||0, NH.au.currentTime + parseFloat(b.dataset.seek))));
});
document.getElementById('jumpback').onclick=()=>{
  NH.seekPrecise(Math.max(0, NH.au.currentTime - NH.VIEW.span));
};
document.getElementById('jumpfwd').onclick=()=>{
  NH.seekPrecise(Math.min(NH.au.duration||0, NH.au.currentTime + NH.VIEW.span));
};
document.querySelectorAll('.off button').forEach(b=>b.onclick=async()=>{
  if(!NH.S) return;
  NH.OFFSET=Math.round((NH.OFFSET+parseFloat(b.dataset.off))*100)/100;
  NH.S.offset=NH.OFFSET;
  document.getElementById('offval').textContent=NH.OFFSET.toFixed(2)+'s';
  NH.syncModes(); drawWave();
  const i=NH.idxAt(NH.au.currentTime);
  if(i>=0) NH.highlight(i);
  await api('/api/pl',{action:'ui_offset', idx:NH.S.idx, offset:NH.OFFSET});
});
document.getElementById('offval').onclick=()=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED) return;
  const el=document.getElementById('offval');
  inlineEdit(el, NH.OFFSET, {min:-10, max:10, fmt:v=>v.toFixed(2), apply:async v=>{
    NH.OFFSET=Math.round(v*100)/100;
    if(NH.S) NH.S.offset=NH.OFFSET;
    el.textContent=NH.OFFSET.toFixed(2)+'s';
    NH.syncModes(); drawWave();
    const i=NH.idxAt(NH.au.currentTime); if(i>=0) NH.highlight(i);
    if(NH.S) await api('/api/pl',{action:'ui_offset', idx:NH.S.idx, offset:NH.OFFSET});
  }});
};

NH.OPEN = new Set();
function saveOpen(){
  fetch('/api/pl',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'ui_open', ids:[...NH.OPEN]})});
}

NH.LOAD_REQUEST = 0;
async function load(i, autoplay, nextEditMode){
  if(NH.LRC_REPLACING) return false;
  clearToast();                                   // 换歌前不留下上一首的提示
  const request=++NH.LOAD_REQUEST;
  const editing=NH.LRCEDIT;
  let d;
  try{
    if(editing){
      NH.setLrcLocked(true);
      if(!await NH.flushLrc()) return false;
      if(request!==NH.LOAD_REQUEST) return false;
    }
    d=await api('/api/song/'+i);
    if(request!==NH.LOAD_REQUEST) return false;
  }catch(e){
    if(request===NH.LOAD_REQUEST) done('加载歌曲失败：'+e.message);
    return false;
  }finally{
    if(editing && request===NH.LOAD_REQUEST) NH.setLrcLocked(false);
  }
  const changedSong=!NH.S || String(NH.S.idx)!==String(d.idx);
  if(changedSong || nextEditMode!==undefined){
    NH.EDITMODE=nextEditMode===true;
    NH.LRCEDIT=false;
    NH.syncModes();
  }
  if(d.pending){                               // 没有歌词 → 先能播，再后台匹配
    NH.S=d; NH.LINES=[]; NH.CUR=-1; NH.NAV=[];
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML='<div class="lm">匹配歌词中…</div>';
    busy('匹配歌词中…');
    document.getElementById('rmcol').innerHTML='';
    if(autoplay || NH.PLAYING===null){            // 单击只换 UI，不打断旧音频
      NH.commitAudio();
      NH.au.playbackRate=+document.getElementById('rate').value;
      if(autoplay) NH.au.play().catch(()=>{});
    }
    lyr.innerHTML='<div class="lm">分离人声，确认是否有人声…</div>';
    const v=(VC.auto_start===false) ? null : await ensureVocals(d.idx);
    if(request!==NH.LOAD_REQUEST) return false;
    if(v && v.state==='done' && v.has_vocals===false){
      lyr.innerHTML='<div class="lm">纯音乐（无人声），不匹配歌词</div>';
      done('这首是纯音乐，跳过歌词匹配');
      return true;
    }
    try{
      await api('/api/pl',{action:'match',idx:d.idx});
      for(let k=0;k<40 && request===NH.LOAD_REQUEST;k++){
        await new Promise(r=>setTimeout(r,1500));
        if(request!==NH.LOAD_REQUEST) return false;
        const d2=await api('/api/song/'+i);
        if(request!==NH.LOAD_REQUEST) return false;
        if(!d2.pending) return load(i, autoplay, nextEditMode);
      }
    }catch(e){
      if(request!==NH.LOAD_REQUEST) return false;
    }
    if(request!==NH.LOAD_REQUEST) return false;
    lyr.innerHTML='<div class="lm">没匹配到歌词（仍可播放）</div>';
    done('这首歌没匹配到歌词，仍可播放');
    return true;
  }
  {
    NH.S=d; NH.LINES=d.lines; NH.CUR=-1;
    if(String(NH.PLAYING) !== String(d.idx)){
      document.querySelectorAll('.ln.on,.ln2.on').forEach(el=>el.classList.remove('on'));
    }
    NH.NAV=NH.LINES.map((l,i)=>l.meta?-1:i).filter(i=>i>=0);
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML=NH.LINES.map((l,n)=>`<div class="ln" data-n="${n}"><span class="tx">${String(n+1).padStart(2,'0')}</span> ${l.ruby}</div>`).join('');
    document.querySelectorAll('.ln').forEach(el=>{
      const n=+el.dataset.n;
      el.onclick=e=>{ if(e.detail>1) return; NH.selectLine(n); };
      el.ondblclick=()=>NH.playLine(n);
    });
    NH.renderSide();
    NH.OFFSET = d.offset || 0;
    document.getElementById('offval').textContent = NH.OFFSET.toFixed(2)+'s';
    NH.syncModes();
    if(NH.LRCEDIT) NH.renderLrcTable();
    else NH.WAVE=null;
    if(NH.PLAYING===null) NH.commitAudio();                 // 第一次载入才绑定音频

    if(autoplay){ NH.commitAudio(); NH.au.play().catch(()=>{}); }
    NH.au.playbackRate=+document.getElementById('rate').value;
  }
  NH.VSTAT=null; paintVStatus();
  if(!NH.LRCEDIT) NH.WAVE=null;
  if(VC.auto_start!==false) ensureVocals(d.idx);
  return true;
}
function navIdx(n){ const k=NH.NAV.indexOf(n); return k<0?0:k; }

NH.TOAST_T = null; NH.TOAST_Q = []; NH.TOAST_BUSY = false; NH.TOAST_SHOWN = false;
function _toastEl(){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; document.body.appendChild(t); }
  return t;
}
function _showToast(msg, ms){
  const t=_toastEl();
  t.textContent=msg; t.classList.add('on'); NH.TOAST_SHOWN=true;
  clearTimeout(NH.TOAST_T);
  NH.TOAST_BUSY = ms===0;
  if(ms>0) NH.TOAST_T=setTimeout(()=>{
    t.classList.remove('on'); NH.TOAST_SHOWN=false; NH.TOAST_BUSY=false; _nextToast();
  }, ms);
}
function _nextToast(){
  if(NH.TOAST_BUSY || !NH.TOAST_Q.length) return;
  const [msg, ms]=NH.TOAST_Q.shift();
  _showToast(msg, ms);
}
function toast(msg, ms=(UI.toast_ms||4200)){
  if(ms===0){ NH.TOAST_Q=[]; _showToast(msg, 0); return; }   // busy：清队列、立即显示
  if(NH.TOAST_BUSY){ _showToast(msg, ms); return; }          // 用结果替换"进行中"
  if(!NH.TOAST_SHOWN){ _showToast(msg, ms); return; }
  if(NH.TOAST_Q.length>=2) NH.TOAST_Q.shift();                  // 最多排两条
  NH.TOAST_Q.push([msg, ms]);
}
function clearToast(){
  NH.TOAST_Q=[]; clearTimeout(NH.TOAST_T); NH.TOAST_BUSY=false; NH.TOAST_SHOWN=false;
  const t=document.getElementById('toast');
  if(t) t.classList.remove('on');
}
NH.BUSY = false;
function lock(btn, on){
  NH.BUSY=on;
  document.querySelectorAll('#rem').forEach(b=>{ if(!b) return;
    b.style.pointerEvents = on ? 'none' : '';
    b.style.opacity = on ? '.45' : '';
  });
  if(btn){ btn.disabled=on; }
}

// 进行中：常驻，等 done() 或新的 toast() 覆盖
function busy(msg){ toast(msg, 0); }
// 一次性结果：几秒后自动消失
function done(msg){ toast(msg, UI.toast_ms||4200); }

async function api(path, body){
  const r=await fetch(path, body?{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)}:undefined);
  if(!r.ok){
    let msg='HTTP '+r.status;
    try{
      const d=await r.clone().json();
      msg=d.error||d.detail||d.message||msg;
    }catch(e){
      try{ const t=await r.text(); if(t) msg=t.length>200?t.slice(0,200):t; }catch(e2){}
    }
    throw new Error(msg);
  }
  return r.json();
}

async function loadLib(){
  const d = await api('/api/pl');
  NH.PLS = d.lists || d;
  if(d.open && d.open.length) NH.OPEN = new Set(d.open);
  NH.LIB = NH.PLS.flatMap(g=>g.items);
  renderList();
}

function applyLists(r){
  if(!r || !r.lists) return;
  NH.PLS = r.lists;
  NH.LIB = NH.PLS.flatMap(g => g.items);
  renderList();
}

function uiPrompt(title, value){
  return new Promise(resolve => {
    const box = document.createElement('div');
    box.className = 'menu';
    box.id = 'uiprompt';
    box.style.cssText = 'position:fixed;left:50%;top:28%;transform:translateX(-50%);min-width:280px;padding:10px;z-index:99';
    const lab = document.createElement('div');
    lab.textContent = title;
    lab.style.cssText = 'font-size:12px;color:#878c95;padding:2px 4px 8px';
    const inp = document.createElement('input');
    inp.className = 'numin';
    inp.value = value || '';
    inp.style.cssText = 'width:100%;box-sizing:border-box;margin-bottom:8px';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const ok = document.createElement('button'); ok.textContent = '确定';
    const cancel = document.createElement('button'); cancel.textContent = '取消';
    row.appendChild(cancel); row.appendChild(ok);
    box.appendChild(lab); box.appendChild(inp); box.appendChild(row);
    box.addEventListener('click', e => e.stopPropagation());
    document.body.appendChild(box);
    const close = v => {
      document.removeEventListener('keydown', key);
      box.remove();
      resolve(v);
    };
    const key = e => {
      if(e.key === 'Escape'){ e.preventDefault(); close(null); }
      else if(e.key === 'Enter'){ e.preventDefault(); close(inp.value.trim() || null); }
    };
    document.addEventListener('keydown', key);
    ok.onclick = () => close(inp.value.trim() || null);
    cancel.onclick = () => close(null);
    inp.focus(); inp.select();
  });
}
NH.uiPrompt = uiPrompt;

function uiConfirm(title, body, danger){
  return new Promise(resolve => {
    const box = document.createElement('div');
    box.className = 'menu';
    box.id = 'uiconfirm';
    box.style.cssText = 'position:fixed;left:50%;top:32%;transform:translateX(-50%);min-width:300px;max-width:520px;padding:12px;z-index:99';
    const h = document.createElement('div');
    h.textContent = title;
    h.style.cssText = 'font-size:13px;color:#e9e7e4;padding:2px 4px 6px';
    const p = document.createElement('div');
    p.textContent = body || '';
    p.style.cssText = 'font-size:12px;color:#878c95;line-height:1.6;padding:0 4px 10px;white-space:pre-wrap';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const cancel = document.createElement('button'); cancel.textContent = '取消';
    const ok = document.createElement('button'); ok.textContent = '确定';
    if(danger) ok.style.color = '#e06c75';
    row.appendChild(cancel); row.appendChild(ok);
    box.appendChild(h); box.appendChild(p); box.appendChild(row);
    box.addEventListener('click', e => e.stopPropagation());
    document.body.appendChild(box);
    const close = v => {
      document.removeEventListener('keydown', key);
      box.remove();
      resolve(v);
    };
    const key = e => {
      if(e.key === 'Escape'){ e.preventDefault(); close(false); }
      else if(e.key === 'Enter'){ e.preventDefault(); close(true); }
    };
    document.addEventListener('keydown', key);
    ok.onclick = () => close(true);
    cancel.onclick = () => close(false);
    cancel.focus();
  });
}
NH.uiConfirm = uiConfirm;

function renderList(){
  const q=(document.getElementById('q').value||'').trim().toLowerCase();
  const hit=x=>!q || (x.orig||'').toLowerCase().includes(q) || (x.title||'').toLowerCase().includes(q)
                 || (x.artist||'').toLowerCase().includes(q);
  let html='';
  NH.PLS.forEach(g=>{
    const its=g.items.filter(hit);
    if(q && !its.length) return;
    const open=q || NH.OPEN.has(g.id);
    html+=`<div class="pl" data-id="${g.id}">
      <div class="plh" draggable="true" data-act="toggle" data-id="${g.id}" title="右键：导入 / 重命名 / 清空 / 删除">
        <span class="car">${open?'▾':'▸'}</span><span class="pln">${g.name}</span>
        <span class="plc">${its.length}</span></div>
      <div class="plb" ${open?'':'hidden'}>`
      + its.map(x=>`<div class="it${NH.SEL_LIST===g.id && NH.SELU.has(x.uid)?' picked':''}" data-i="${x.idx}" data-u="${x.uid}" data-hl="${x.has_lyric===false?0:1}" draggable="true">
          <div class="t1"><span class="orig">${x.orig||x.title}</span>
            ${(x.orig||'')===(x.title||'')?'':`<span class="mch">${x.title}</span>`}</div>
          <div class="ar">${x.artist}</div>
          <b class="del" data-act="del-entry" data-u="${x.uid}" data-id="${g.id}" title="从歌单移除">✕</b>
        </div>`).join('')
      + `</div></div>`;
  });
  document.getElementById('list').innerHTML=html||'<div class="empty">没有歌</div>';
}

function paintSongSel(){
  document.querySelectorAll('.it').forEach(el=>{
    const pl=el.closest('.pl');
    el.classList.toggle('picked',
      !!pl && NH.SEL_LIST===pl.dataset.id && NH.SELU.has(el.dataset.u));
  });
}
function clearSongSel(){
  NH.SELU.clear(); NH.SEL_LIST=null; NH.SEL_ANCHOR=null; paintSongSel();
}
function songUidsVisible(lid){
  const pl=document.querySelector('.pl[data-id="'+lid+'"]');
  return pl ? [...pl.querySelectorAll('.it')].map(x=>x.dataset.u) : [];
}
function selectSongRange(lid, uid){
  if(NH.SEL_LIST!==lid){ NH.SELU.clear(); NH.SEL_LIST=lid; NH.SEL_ANCHOR=null; }
  const uids=songUidsVisible(lid);
  let b=uids.indexOf(uid);
  if(b<0) return;
  let a=uids.indexOf(NH.SEL_ANCHOR);
  if(a<0) a=b;
  NH.SELU=new Set(uids.slice(Math.min(a,b), Math.max(a,b)+1));
  if(!NH.SEL_ANCHOR) NH.SEL_ANCHOR=uid;
  paintSongSel();
}

// 歌单右键菜单：导入 / 重命名 / 清空 / 删除
function closeCtx(){
  document.getElementById('ctxmenu')?.remove();
  document.getElementById('songctx')?.remove();
}
function openPlMenu(x, y, g){
  closeCtx();
  const box=document.createElement('div');
  box.className='menu'; box.id='ctxmenu'; box.style.minWidth='150px';
  const mk=(label, fn, danger)=>{
    const b=document.createElement('button'); b.textContent=label;
    if(danger) b.style.color='#e06c75';
    b.onclick=ev=>{ ev.stopPropagation(); closeCtx(); fn(); };
    box.appendChild(b);
  };
  mk('导入音乐…', ()=>doImport(g.id));
  if(!g.locked) mk('重命名…', async ()=>{
    const name=await uiPrompt('新的歌单名', g.name);
    if(!name || name===g.name) return;
    const r=await api('/api/pl',{action:'list_rename',id:g.id,name});
    applyLists(r);
  });
  mk('清空歌单', async ()=>{
    if(!await uiConfirm(`清空「${g.name}」？`, '歌本身不会丢')) return;
    const r=await api('/api/pl',{action:'list_clear',id:g.id});
    applyLists(r);
  });
  if(!g.locked) mk('删除歌单', async ()=>{
    if(!await uiConfirm(`删除歌单「${g.name}」？`, '歌本身不会丢', true)) return;
    const r=await api('/api/pl',{action:'list_delete',id:g.id});
    applyLists(r);
  }, true);
  document.body.appendChild(box);
  const r=box.getBoundingClientRect();
  box.style.left=Math.min(x, window.innerWidth-r.width-8)+'px';
  box.style.top=Math.min(y, window.innerHeight-r.height-8)+'px';
}
function openSongMenu(x, y, lid, uids){
  closeCtx();
  const box=document.createElement('div');
  box.className='menu'; box.id='songctx'; box.style.minWidth='170px';
  const n=uids.length;
  const b=document.createElement('button');
  b.textContent = n===1 ? '从歌单移除' : `移除选中的 ${n} 首`;
  b.style.color='#e06c75';
  b.onclick=async ev=>{
    ev.stopPropagation(); closeCtx();
    const ok=await uiConfirm(n===1?'从歌单移除？':`移除选中的 ${n} 首？`, '歌本身不会丢', true);
    if(!ok) return;
    const r=await api('/api/pl',{action:'entries_remove',list:lid,uids});
    NH.SELU.clear(); NH.SEL_LIST=null; NH.SEL_ANCHOR=null;
    applyLists(r);
  };
  box.appendChild(b);
  document.body.appendChild(box);
  const r=box.getBoundingClientRect();
  box.style.left=Math.min(x, window.innerWidth-r.width-8)+'px';
  box.style.top=Math.min(y, window.innerHeight-r.height-8)+'px';
}

document.getElementById('list').addEventListener('contextmenu', e=>{
  const row=e.target.closest('.it');
  if(row){
    e.preventDefault();
    const pl=row.closest('.pl');
    const lid=pl.dataset.id, uid=row.dataset.u;
    if(NH.SEL_LIST!==lid || !NH.SELU.has(uid)){
      NH.SELU=new Set([uid]); NH.SEL_LIST=lid; NH.SEL_ANCHOR=uid; paintSongSel();
    }
    openSongMenu(e.clientX, e.clientY, lid, [...NH.SELU]);
    return;
  }
  const h=e.target.closest('.plh');
  if(!h) return;
  e.preventDefault();
  const g=NH.PLS.find(x=>x.id===h.dataset.id);
  if(g) openPlMenu(e.clientX, e.clientY, g);
});
document.addEventListener('click', closeCtx);
document.addEventListener('keydown', e=>{
  if(e.key==='Escape') closeCtx(); });

// 一次事件委托，避免重复绑定
document.getElementById('list').addEventListener('click', async e=>{
  const delEntry=e.target.closest('[data-act="del-entry"]');
  if(delEntry){
    e.stopPropagation();
    const lid=delEntry.dataset.id, uid=delEntry.dataset.u;
    const r=await api('/api/pl',{action:'entry_remove',list:lid,uid});
    if(NH.SEL_LIST===lid) NH.SELU.delete(uid);
    applyLists(r); paintSongSel();
    return;
  }

  const head=e.target.closest('[data-act="toggle"]');
  if(head){ const id=head.dataset.id;
    NH.OPEN.has(id)?NH.OPEN.delete(id):NH.OPEN.add(id); saveOpen(); return renderList(); }

  const row=e.target.closest('.it');
  if(row){
    const lid=row.closest('.pl').dataset.id, uid=row.dataset.u;
    if(e.shiftKey){ e.preventDefault(); selectSongRange(lid, uid); return; }
    if(e.metaKey||e.ctrlKey){
      e.preventDefault();
      if(NH.SEL_LIST!==lid){ NH.SELU.clear(); NH.SEL_LIST=lid; NH.SEL_ANCHOR=null; }
      NH.SELU.has(uid)?NH.SELU.delete(uid):NH.SELU.add(uid);
      NH.SEL_ANCHOR=uid; paintSongSel(); return;
    }
    clearSongSel();
    NH.SEL_LIST=lid; NH.SEL_ANCHOR=uid;
    load(row.dataset.i);
  }
});
document.getElementById('list').addEventListener('dblclick', e=>{
  const row=e.target.closest('.it');
  if(row) load(row.dataset.i, true);
});
document.getElementById('list').addEventListener('dragstart', e=>{
  const row=e.target.closest('.it'), head=e.target.closest('.plh');
  if(row){ const pl=row.closest('.pl');
    NH.DRAG={kind:'song', uid:row.dataset.u, from:pl.dataset.id};
    e.dataTransfer.setData('text/plain','song'); }
  else if(head){ const pl=head.parentElement;
    if(pl.dataset.id==='default'){ NH.DRAG=null; return; }   // 默认歌单固定置顶
    NH.DRAG={kind:'list', id:pl.dataset.id};
    e.dataTransfer.setData('text/plain','list'); }
});
document.getElementById('list').addEventListener('dragover', e=>{
  if(e.target.closest('.it')||e.target.closest('.plh')||e.target.closest('.plb')) e.preventDefault();
});
document.getElementById('list').addEventListener('drop', async e=>{
  if(!NH.DRAG) return;
  const targetRow=e.target.closest('.it');
  const targetPl=(e.target.closest('.pl')||{}).dataset;
  const toPl=targetPl && targetPl.id;
  if(NH.DRAG.kind==='song'){
    if(!toPl) return;
    if(targetRow){                                   // 落在某首歌上 → 插到它前面
      const uids=[...e.target.closest('.plb').querySelectorAll('.it')].map(x=>x.dataset.u);
      if(NH.DRAG.from===toPl){
        const arr=uids.filter(u=>u!==NH.DRAG.uid);
        arr.splice(arr.indexOf(targetRow.dataset.u), 0, NH.DRAG.uid);
        await api('/api/pl',{action:'entry_reorder',list:toPl,uids:arr});
      }else{
        await api('/api/pl',{action:'entry_move',from:NH.DRAG.from,to:toPl,uid:NH.DRAG.uid});
      }
    }else{                                           // 落在歌单空白处 → 移过去
      if(NH.DRAG.from!==toPl) await api('/api/pl',{action:'entry_move',from:NH.DRAG.from,to:toPl,uid:NH.DRAG.uid});
    }
  }else if(NH.DRAG.kind==='list' && toPl && NH.DRAG.id!==toPl){
    const ids=[...document.querySelectorAll('.pl')].map(x=>x.dataset.id).filter(x=>x!=='default');
    ids.splice(ids.indexOf(NH.DRAG.id),1);
    ids.splice(ids.indexOf(toPl),0,NH.DRAG.id);
    await api('/api/pl',{action:'list_reorder',ids});
  }
  NH.DRAG=null; loadLib();
});

// 导入：选完直接导入，只弹一条消息
async function doImport(listId, btn){
  let paths=[];
  const api_ = window.pywebview && window.pywebview.api;
  if(api_ && api_.pick_any){
    paths = await api_.pick_any() || [];        // 一个对话框，文件/文件夹都行
  }else if(api_ && api_.pick_folder){
    const p = await api_.pick_folder(); if(p) paths=[p];
  }else{
    paths = ((await uiPrompt('路径（多个用 ; 分隔）'))||'').split(';').map(x=>x.trim()).filter(Boolean);
  }
  if(!paths.length) return;
  busy('导入中…');
  try{
    const r = await api('/api/pl',{action:'import', list:listId, paths});
    if(r.lists) NH.PLS=r.lists; NH.LIB=NH.PLS.flatMap(g=>g.items); renderList();
    if(r.ok===false){ done(r.error||'导入失败'); return; }
    const bits=[`新增 ${r.imported} 首`];
    if(r.pending_count) bits.push(`其中 ${r.pending_count} 首待匹配歌词`);
    if(r.overwritten) bits.push(`覆盖 ${r.overwritten} 首歌词`);
    if(r.unpaired) bits.push(`${r.unpaired} 个 lrc 未配对`);
    if(r.already) bits.push(`${r.already} 首已在歌单`);
    done(bits.join('，')); lock(btn, false);
  }catch(err){
    done('导入失败：'+err.message); lock(btn, false);
  }
}

document.getElementById('newlist').onclick=async e=>{
  e.stopPropagation();
  const name=await uiPrompt('新歌单名称'); if(!name) return;
  const r=await api('/api/pl',{action:'list_create',name});
  applyLists(r);
};
loadLib().catch(async()=>{            // 启动偶发失败 → 延迟重试一次
  await new Promise(r=>setTimeout(r,600));
  loadLib().catch(e=>toast('加载歌单失败：'+e.message));
});

document.getElementById('resetall').onclick=async()=>{
  if(!NH.S) return;
  await api('/api/pl',{action:'edit_clear', idx:NH.S.idx});
  toast('已恢复默认标注');
  load(NH.S.idx);
};

Object.assign(NH, {lyr, CFG, UI, VC, cv, cx, SPAN_MIN, SPAN_MAX, clampStart, viewStart, SPAN_LO, SPAN_HI, spanText, updateWaveHint, syncWaveLabels, syncFollow, setWaveSpan, inlineEdit, measureCanvas, fitCanvas, drawWave, fmt, paintVStatus, ensureVocals, pollVocals, loadWave, saveOpen, load, navIdx, _toastEl, _showToast, _nextToast, toast, clearToast, lock, busy, done, api, loadLib, renderList, closeCtx, openPlMenu, doImport});
})();
