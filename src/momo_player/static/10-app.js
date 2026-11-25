/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
NH.TOKEN = window.__MOMO_TOKEN || '';
// 播放器 · 界面与逻辑总入口（按加载顺序共享全局作用域）
// 文件划分（player.html 里按顺序加载）：
//   10-app.js     状态、工具、歌单、载入单曲、右侧面板
//   20-editor.js  LRC 编辑表格（对齐、增删、粘贴、保存）
//   30-playback.js 统一时间语义、自绘播放条、波形跟随、键盘
NH.S = null; NH.LINES = []; NH.NAV = []; NH.CUR = -1; NH.loop = false;
NH.ST_ON = false; NH.ST_URL = null; NH.ST_UID = null; NH.ST_SPEED = 1; NH.MODE = 'rm'; NH.PLAYING_UID = null; NH.VIEW_MODE = 'normal'; NH.LRC_VERSION = null; NH.NO_MATCH = new Set(); NH.AUTO_REBUILD = false;
NH.isSelfPlaying = () => !!(NH.S && NH.PLAYING_UID !== null && String(NH.PLAYING_UID) === String(NH.S.uid));
const lyr=document.getElementById('lyr');
NH.LIB = []; NH.PLS = []; NH.DRAG = null;
NH.SELU = new Set(); NH.SEL_LIST = null; NH.SEL_ANCHOR = null;
NH.WMARK = {};   // 查看歌曲的波形播放头（静止时用）

// ── 波形与整体偏移 ────────────────────────────────
const CFG=(window.__CFG)||{};
const UI=(CFG.player&&CFG.player.ui)||{};
const JOB=(CFG.jobs)||{};
const WAVE_DRAW_MS = 32;   // 波形播放时的重绘节流；实现常量，不进配置
NH.WAVE = null; NH.VIEW = {span:UI.wave_span||5}; NH.OFFSET = 0; NH.FOLLOW = true; NH.DRAWN = null;
const cv=document.getElementById('wave'), cx=cv.getContext('2d');
if(cv.style) cv.style.height=(UI.wave_height||120)+'px';
const SPAN_MIN=UI.wave_span_min||2, SPAN_MAX=UI.wave_span_max||10;   // 秒

function themeColor(name, fallback){
  try{
    const v=getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }catch(e){ return fallback; }
}

NH.PAN_START = 0;
function clampStart(st, span){
  const dur=(NH.WAVE && NH.WAVE.duration) || 0;
  return Math.max(0, Math.min(Math.max(0, dur-span), st));
}
function waveMarker(idx){
  const v=NH.WMARK[idx]; return v==null ? 0 : v;
}
function audioTime(t){ return NH.ST_ON ? t / (NH.ST_SPEED || 1) : t; }
function sourceTime(t){ return NH.ST_ON ? t * (NH.ST_SPEED || 1) : t; }
function waveTime(){
  if(NH.isSelfPlaying()) return sourceTime(NH.au.currentTime || 0);
  const m=NH.WMARK[NH.S && NH.S.uid];
  if(m!=null) return m;
  if(NH.VIEW_MODE==='lrc' && NH.ESEL >= 0){
    const l=NH.EROWS[NH.ESEL];
    if(l && l.t != null) return l.t + NH.OFFSET;
  }
  if(NH.VIEW_MODE!=='lrc' && NH.CUR >= 0){
    const l=NH.LINES[NH.CUR];
    if(l && l.t != null) return l.t + NH.OFFSET;
  }
  return NH.MARK != null ? NH.MARK : 0;
}
function setWaveMarker(t, select){
  if(!NH.S) return;
  const dur=(NH.WAVE && NH.WAVE.duration) || NH.S.duration || 0;
  t=Math.max(0, dur ? Math.min(dur, +t||0) : +t||0);
  NH.WMARK[NH.S.uid]=t; NH.MARK=t;
  if(select){
    const i=nearestWaveRow(t);
    if(i>=0){
      if(NH.VIEW_MODE==='lrc'){ NH.ESEL=i; NH.paintSelection(); }
      else NH.highlight(i);
    }
  }
  drawWave();
}
function waveStep(delta){
  if(!NH.S) return;
  const self=NH.isSelfPlaying();
  const base=self ? sourceTime(NH.au.currentTime||0) : waveMarker(NH.S.uid);
  const dur=self ? sourceTime(NH.au.duration||0) : ((NH.WAVE&&NH.WAVE.duration)||NH.S.duration||0);
  const t=Math.max(0, dur ? Math.min(dur, base+delta) : base+delta);
  NH.WMARK[NH.S.uid]=t; NH.MARK=t;
  if(self) NH.seekPrecise(audioTime(t));
  else {
    const i=nearestWaveRow(t);
    if(i>=0){
      if(NH.VIEW_MODE==='lrc'){ NH.ESEL=i; NH.paintSelection(); }
      else NH.highlight(i);
    }
  }
  drawWave();
  const el=document.getElementById('mark');
  if(el){ el.textContent='标记：'+NH.lrcFmt(t); el.classList.add('set'); }
}
function nearestWaveRow(t){
  const ls=NH.viewLines(); let n=-1, best=1e9;
  ls.forEach((l,i)=>{
    if(!l || NH.isMetaLine(l) || NH.lineT(l)===null) return;
    const d=Math.abs(NH.lineT(l)-t);
    if(d<best){ best=d; n=i; }
  });
  return n;
}
function viewStart(){
  const dur=(NH.WAVE && NH.WAVE.duration) || 0;
  const span=Math.min(NH.VIEW.span, dur||NH.VIEW.span);
  if(!NH.FOLLOW) return {start:clampStart(NH.PAN_START, span), span};
  let s0=waveTime() - span/2;
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
  cx.strokeStyle=themeColor('--wave-fill','#4a7f6b'); cx.beginPath();
  for(let i=i0;i<i1;i++){
    const x=Math.round((i*step-start)/perPx);
    const [mn,mx]=peaks[i];
    cx.moveTo(x+0.5, mid-mx*mid*0.95);
    cx.lineTo(x+0.5, mid-mn*mid*0.95);
  }
  cx.stroke();
  // 只要"每一句开头的线"，其他辅助线一律不画
  {
    const ls = NH.VIEW_MODE==='lrc' ? NH.EROWS : NH.LINES;
    cx.strokeStyle=themeColor('--amber','#c8843f'); cx.globalAlpha=.62;   // 暖橙色，和绿色波形、亮绿播放头区分开
    cx.lineWidth=1; cx.beginPath();
    (ls||[]).forEach(l=>{
      if(!l || l.t==null) return;
      const lt=l.t+NH.OFFSET;
      if(lt<start || lt>start+span) return;
      const lx=Math.round((lt-start)/perPx)+0.5;
      cx.moveTo(lx,0); cx.lineTo(lx,h);
    });
    cx.stroke();
    cx.globalAlpha=1;
  }
  // 播放头：B 在播跟音频，否则跟选中行
  const x=Math.round((waveTime()-start)/perPx);
  cx.strokeStyle=themeColor('--accent-soft','#7fbfa6'); cx.beginPath(); cx.moveTo(x+0.5,0); cx.lineTo(x+0.5,h); cx.stroke();
}
function fmt(t){ const m=Math.floor(t/60), s=Math.round(t%60); return `${m}:${String(s).padStart(2,'0')}`; }

async function waitJob(id, onState){
  for(;;){
    const st=await api('/api/jobs/'+id);
    if(onState) onState(st);
    if(st.state==='done' || st.state==='failed' || st.state==='canceled') return st;
    await new Promise(r=>setTimeout(r, JOB.poll_ms||1000));
  }
}
async function loadWave(force){
  if(!NH.S) return;
  if(!force && NH.WAVE) return;
  const uid=NH.S.uid, seq=NH.track('wave');
  NH.WAVE=null;
  try{
    const src=(NH.VSTAT && NH.VSTAT.state==='done' && NH.VSTAT.has_vocals) ? '?src=vocals' : '';
    const d=await api('/api/wave/'+encodeURIComponent(uid)+src);
    if(!NH.isCurrent('wave',seq) || !NH.S || String(NH.S.uid)!==String(uid)) return;
    if(d.error){ document.getElementById('wavehint').textContent='无法生成波形：'+d.error; return; }
    NH.WAVE=d;
    updateWaveHint();
    drawWave();
  }catch(e){
    if(!NH.isCurrent('wave',seq) || !NH.S || String(NH.S.uid)!==String(uid)) return;
    document.getElementById('wavehint').textContent='波形加载失败';
  }
}
(function waveLoop(){
  let last=0;
  function tick(ts){
    if(NH.WAVE && NH.VIEW_MODE==='lrc' && NH.isSelfPlaying() && !NH.au.paused && ts-last>=WAVE_DRAW_MS){ drawWave(); last=ts; }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
document.getElementById('wavefollow').onclick=()=>{
  if(NH.FOLLOW){
    NH.PAN_START = viewStart().start;    // 先冻结当前窗口，再关
    NH.FOLLOW = false;
  }else{
    NH.FOLLOW = true;
  }
  syncFollow();
};
cv.addEventListener('contextmenu', e=>e.preventDefault());
// 双指滑动（触控板）/ 滚轮：左右平移窗口（竖向滑动也当横向用）
cv.addEventListener('wheel', e=>{
  if(!NH.WAVE) return;
  e.preventDefault();
  const d=e.deltaX || e.deltaY;
  if(!d) return;
  const v=viewStart();                   // 先记住当前看到的窗口
  if(NH.FOLLOW){                         // 手动拖 → 自动关跟随，冻结原地
    NH.PAN_START=v.start;
    NH.FOLLOW=false;
    syncFollow();
  }
  const w=cv.getBoundingClientRect().width || 1;
  NH.PAN_START=clampStart(v.start + d*v.span/w, v.span);
  drawWave();
}, {passive:false});
cv.addEventListener('click', e=>{
  if(!NH.WAVE || e.button===2) return;
  const r=cv.getBoundingClientRect();
  const ratio=Math.max(0, Math.min(1,(e.clientX-r.left)/r.width));
  const v=NH.DRAWN || viewStart();                 // 所见即所得
  const t=Math.round((v.start + ratio*v.span)*100)/100;
  setWaveMarker(t, true);
  if(NH.isSelfPlaying()) NH.seekPrecise(audioTime(t));
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
  waveStep(parseFloat(b.dataset.seek));
});
document.getElementById('jumpback').onclick=()=>{ waveStep(-NH.VIEW.span); };
document.getElementById('jumpfwd').onclick=()=>{ waveStep(NH.VIEW.span); };
document.querySelectorAll('.off button').forEach(b=>b.onclick=async()=>{
  if(!NH.S) return;
  NH.OFFSET=Math.round((NH.OFFSET+parseFloat(b.dataset.off))*100)/100;
  NH.S.offset=NH.OFFSET;
  document.getElementById('offval').textContent=NH.OFFSET.toFixed(2)+'s';
  NH.syncModes(); drawWave();
  const i=NH.idxAt(NH.au.currentTime);
  if(i>=0) NH.highlight(i);
  const r=await api('/api/pl',{action:'ui_offset', uid:NH.S.uid, offset:NH.OFFSET});
  if(r && r.ok===false) done(r.error||'歌曲已不可用');
});
document.getElementById('offval').onclick=()=>{
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED) return;
  const el=document.getElementById('offval');
  inlineEdit(el, NH.OFFSET, {min:-10, max:10, fmt:v=>v.toFixed(2), apply:async v=>{
    NH.OFFSET=Math.round(v*100)/100;
    if(NH.S) NH.S.offset=NH.OFFSET;
    el.textContent=NH.OFFSET.toFixed(2)+'s';
    NH.syncModes(); drawWave();
    const i=NH.idxAt(NH.au.currentTime); if(i>=0) NH.highlight(i);
    if(NH.S){
      const r=await api('/api/pl',{action:'ui_offset', uid:NH.S.uid, offset:NH.OFFSET});
      if(r && r.ok===false) done(r.error||'歌曲已不可用');
    }
  }});
};

NH.OPEN = new Set();
function saveOpen(){
  return api('/api/pl',{action:'ui_open', ids:[...NH.OPEN]})
    .catch(err=>reportClientError('ui_open', err.message));
}

async function load(ref, autoplay, nextMode){
  if(NH.LRC_REPLACING) return false;
  clearToast();                                   // 换歌前不留下上一首的提示
  const request=NH.track('load');
  NH.viewDispatch({type:'LOAD_START', idx:ref, request});
  NH.syncModes?.();
  const editing=NH.VIEW_MODE==='lrc';
  if(!editing){                                  // 点击后立即切换标题，别等接口
    const it=NH.LIB.find(x=>String(x.uid)===String(ref));
    if(it){
      document.getElementById('vtitle').textContent=it.title+(it.artist?' · '+it.artist:'');
      lyr.innerHTML='';
      document.getElementById('rmcol').innerHTML='';
    }
  }
  let d;
  try{
    if(editing){
      NH.setLrcLocked(true);
      if(!await NH.flushLrc()) return false;
      if(!NH.isCurrent('load',request)) return false;
    }
    d=await api('/api/song/'+encodeURIComponent(ref));
    if(!NH.isCurrent('load',request)) return false;
    NH.LRC_VERSION = d.version || 'none';
    NH.syncLyricMark(d.uid, !!(d.lines && d.lines.length) && !d.disabled);
    NH.markShufflePlayed?.(d.uid);
  }catch(e){
    if(NH.isCurrent('load',request)){
      NH.viewDispatch({type:'LOAD_FAILED', idx:ref, request, error:e.message});
      NH.syncModes?.();
      done('加载歌曲失败：'+e.message);
    }
    return false;
  }finally{
    if(editing && NH.isCurrent('load',request)) NH.setLrcLocked(false);
  }
  if(NH.loop && (NH.PLAYING_UID===null || String(NH.PLAYING_UID)!==String(d.uid))) NH.closeLineLoop?.();
  const changedSong=!NH.S || String(NH.S.uid)!==String(d.uid);
  if(changedSong) NH.track('wave');   // 旧波形请求作废
  if(changedSong){ NH.VSTAT=null; NH.VSTAT_IDX=null; NH.paintVStatus?.(); }
  if(changedSong || nextMode!==undefined){
    NH.VIEW_MODE=nextMode || 'normal';
    NH.syncModes();
  }
  if(d.pending){                               // 没有歌词 → 先能播，再后台匹配
    const knownNoMatch=NH.NO_MATCH.has(String(d.uid));
    NH.viewDispatch({type:'LOAD_PENDING', idx:d.uid, request});
    if(knownNoMatch){
      NH.viewDispatch({type:'LOAD_FAILED', idx:d.uid, request, error:'no lyrics'});
    }else{
      NH.viewDispatch({type:'MATCH_START', idx:d.uid, request});
    }
    NH.syncModes?.();
    NH.S=d; NH.LINES=[]; NH.CUR=-1; NH.NAV=[];
    NH.syncBackPlaying?.();
    NH.paintTicks?.();
    NH.syncModes?.();   // 已有查看歌曲：开始可用，匹配中其他入口仍禁用
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    document.getElementById('rmcol').innerHTML='';
    if(autoplay || NH.PLAYING_UID===null){            // 单击只换 UI，不打断旧音频
      NH.commitAudio();
      if(autoplay) NH.playFromStart?.();
    }
    if(knownNoMatch){                             // 已确认没歌词：不再重跑匹配
      NH.syncModes?.();
      lyr.innerHTML='';
      NH.startVocals(d.uid);
      return true;
    }
    lyr.innerHTML='';
    NH.startVocals(d.uid);
    busy('匹配歌词中…');
    let d2=null;
    try{
      const job=await api('/api/jobs',{kind:'match', uid:d.uid});
      const st=await waitJob(job.id);
      if(!NH.isCurrent('load',request)) return false;
      if(st.state==='failed') throw new Error(st.error || '匹配失败');
      d2=await api('/api/song/'+encodeURIComponent(d.uid));
      if(!NH.isCurrent('load',request)) return false;
      if(!d2.pending) return load(d.uid, false, nextMode);   // 只刷新歌词，不重绑/重置音频
    }catch(e){
      if(!NH.isCurrent('load',request)) return false;
    }
    if(!NH.isCurrent('load',request)) return false;
    const matchStatus = (d2 && d2.match_status) || d.match_status || 'no_match';
    if(matchStatus !== 'network_error') NH.NO_MATCH.add(String(d.uid));
    NH.viewDispatch({type:'MATCH_FAILED', idx:d.uid, request, error:matchStatus});
    NH.syncModes?.();
    lyr.innerHTML='';
    const msg = matchStatus==='network_error' ? '网络请求失败，暂未匹配到歌词'
      : matchStatus==='no_lyrics' ? '找到了候选，但没有可用歌词'
      : '这首歌没匹配到歌词，仍可播放';
    done(msg);
    return true;
  }
  {
    NH.viewDispatch({type:'LOAD_READY', idx:d.uid, request});
    NH.NO_MATCH.delete(String(d.uid));
    NH.S=d; NH.LINES=d.lines; NH.CUR=-1;
    NH.syncBackPlaying?.();
    NH.paintTicks?.();
    if(String(NH.PLAYING_UID) !== String(d.uid)){
      document.querySelectorAll('.ln.on,.ln2.on').forEach(el=>el.classList.remove('on'));
    }
    NH.NAV=NH.LINES.map((l,i)=>l.meta?-1:i).filter(i=>i>=0);
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML=NH.LINES.map((l,n)=>{
      const tr=l.trans ? `<div class="lntrans">${String(l.trans).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>` : '';
      return `<div class="ln" data-n="${n}" data-lid="${l.lid||''}"><span class="tx">${String(n+1).padStart(2,'0')}</span> ${l.ruby}${tr}</div>`;
    }).join('');
    document.querySelectorAll('.ln').forEach(el=>{
      const n=+el.dataset.n;
      el.onclick=e=>{ if(e.detail>1) return; NH.selectLine(n); };
      el.ondblclick=()=>NH.playLine(n);
    });
    NH.renderSide();
    NH.OFFSET = d.offset || 0;
    document.getElementById('offval').textContent = NH.OFFSET.toFixed(2)+'s';
    NH.syncModes();
    if(NH.VIEW_MODE==='lrc') NH.renderLrcTable();
    else NH.WAVE=null;
    if(NH.PLAYING_UID===null) NH.commitAudio();                 // 第一次载入才绑定音频

    if(autoplay){ NH.commitAudio(); NH.playFromStart?.(); }
  }
  NH.VSTAT=null; NH.VSTAT_IDX=null; NH.paintVStatus?.();
  if(NH.VIEW_MODE!=='lrc') NH.WAVE=null;
  NH.startVocals(d.uid);
  return true;
}

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

function authHeaders(extra){
  const h = Object.assign({}, extra || {});
  if(NH.TOKEN) h['X-Momo-Token'] = NH.TOKEN;
  return h;
}
async function api(path, body){
  const headers = authHeaders(body ? {'Content-Type':'application/json'} : {});
  const opts = body ? {method:'POST',headers,body:JSON.stringify(body)}
                    : (Object.keys(headers).length ? {headers} : undefined);
  const r=await fetch(path, opts);
  if(!r.ok){
    let msg='HTTP '+r.status;
    try{
      const d=await r.clone().json();
      if(r.status===409 && d && d.ok===false) return d;   // 版本冲突是业务结果，不是网络失败
      msg=d.error||d.detail||d.message||msg;
    }catch(e){
      try{ const t=await r.text(); if(t) msg=t.length>200?t.slice(0,200):t; }catch(e2){}
    }
    throw new Error(msg);
  }
  return r.json();
}

function openDialog(opts){
  return new Promise(resolve => {
    const {id, title, body, input, okText='确定', cancelText='取消', danger=false,
           extraText='', extraValue=null} = opts;
    const back = document.createElement('div');
    back.className = 'dialog-backdrop';
    const box = document.createElement('div');
    box.className = 'dialog';
    box.id = id;
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');

    const h = document.createElement('div');
    h.className = 'dialog-title';
    h.textContent = title;
    box.appendChild(h);

    if(body){
      const p = document.createElement('div');
      p.className = 'dialog-body';
      p.textContent = body;
      box.appendChild(p);
    }

    let inp = null;
    if(input){
      inp = document.createElement('input');
      inp.className = 'dialog-input';
      inp.value = opts.value || '';
      inp.maxLength = opts.maxLength || 200;
      box.appendChild(inp);
    }

    const row = document.createElement('div');
    row.className = 'dialog-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.textContent = cancelText;
    const ok = document.createElement('button');
    ok.type = 'button'; ok.textContent = okText;
    ok.className = 'primary' + (danger ? ' danger' : '');
    row.appendChild(cancel); row.appendChild(ok);
    let extra = null;
    if(extraText){
      extra = document.createElement('button');
      extra.type = 'button'; extra.textContent = extraText;
      row.insertBefore(extra, cancel);
    }
    box.appendChild(row);

    back.appendChild(box);
    back.addEventListener('click', e => {
      if(e.target === back) finish(input ? null : false);
    });
    box.addEventListener('click', e => e.stopPropagation());
    document.body.appendChild(back);

    const finish = v => {
      document.removeEventListener('keydown', key);
      back.remove();
      resolve(v);
    };
    const key = e => {
      if(e.isComposing || e.keyCode === 229) return;
      if(e.key === 'Escape'){ e.preventDefault(); finish(input ? null : false); }
      else if(e.key === 'Enter'){
        e.preventDefault();
        if(input && !inp.value.trim()) return;
        if(!input && extra && document.activeElement === extra){
          finish(extraValue);
          return;
        }
        if(!input && document.activeElement === cancel){ finish(false); return; }
        finish(input ? (inp.value.trim() || null) : true);
      }
    };
    document.addEventListener('keydown', key);

    const submit = () => {
      if(input && !inp.value.trim()) return;
      finish(input ? (inp.value.trim() || null) : true);
    };
    const dismiss = () => finish(input ? null : false);
    ok.onclick = submit;
    cancel.onclick = dismiss;
    if(extra) extra.onclick = () => finish(extraValue);

    if(inp){
      const sync = () => { ok.disabled = !inp.value.trim(); };
      inp.addEventListener('input', sync);
      sync();
      inp.focus(); inp.select();
    }else{
      cancel.focus();
    }
  });
}

function uiPrompt(title, value){
  return openDialog({id:'uiprompt', title, value, input:true});
}
NH.uiPrompt = uiPrompt;

function uiConfirm(title, body, danger){
  return openDialog({id:'uiconfirm', title, body, danger, input:false});
}
NH.uiConfirm = uiConfirm;

function uiLrcConflict(){
  return openDialog({
    id:'lrcconflict',
    title:'服务端歌词已更新',
    body:'重新加载会放弃本地草稿；用本地覆盖会覆盖服务端最新修改。',
    okText:'用本地覆盖',
    cancelText:'取消',
    extraText:'重新加载服务端',
    extraValue:'reload',
    danger:true,
    input:false
  });
}
NH.uiLrcConflict = uiLrcConflict;

function reportClientError(kind, message, stack, extra){
  try{
    const msg=String(message||'unknown').slice(0,500);
    const key=kind+'|'+msg;
    const now=Date.now();
    if(_ERR_SEEN.get(key) && now-_ERR_SEEN.get(key)<10000) return;
    _ERR_SEEN.set(key, now);
    if(_ERR_SEEN.size>50){
      for(const [k,t] of _ERR_SEEN) if(now-t>60000) _ERR_SEEN.delete(k);
    }
    const ctx=Object.assign({
      phase: NH.VSTATE && NH.VSTATE.phase,
      mode: NH.VIEW_MODE,
      idx: NH.S && NH.S.idx,
      page: (typeof location!=='undefined' ? location.pathname : '')
    }, extra||{});
    fetch('/api/log',{method:'POST',headers:authHeaders({'Content-Type':'application/json'}),
      body:JSON.stringify({kind, message:msg, stack:String(stack||'').slice(0,4000), context:ctx})
    }).catch(()=>{});
  }catch(e){}
}
NH.reportClientError=reportClientError;

window.addEventListener('error', e=>{
  if(e.target && e.target!==window) return;      // 资源加载失败不当作 JS 异常
  const err=e.error;
  reportClientError('js_error', (err&&err.message)||e.message, err&&err.stack);
});
window.addEventListener('unhandledrejection', e=>{
  const r=e.reason;
  reportClientError('js_rejection', (r&&r.message)||String(r||'unhandled rejection'), r&&r.stack);
});


document.getElementById('resetall').onclick=async()=>{
  if(!NH.S) return;
  if(!await NH.uiConfirm('恢复默认标注？', '当前读音和标注会丢失，且无法撤销。', true)) return;
  const song=NH.S, version=NH.LRC_VERSION, request=NH.currentToken('load');
  const r=await api('/api/pl',{action:'edit_clear', uid:song.uid, version});
  // 响应回来前已经发起了别的 load（即使还没完成）→ 让那次切歌继续。
  if(!NH.isCurrent('load',request) || NH.S!==song) return;
  if(r && r.ok===false){ done(r.error||'歌曲已不可用'); await NH.loadLib(); return; }
  if(r && r.version) NH.LRC_VERSION=r.version;
  toast('已恢复默认标注');
  const wasLrc=NH.VIEW_MODE==='lrc';
  if(!await load(NH.S.uid)) return;
  if(wasLrc && NH.VIEW_MODE==='lrc') await NH.openLrcEditor();
};

function applyTheme(theme, persist){
  const light = theme === 'light';
  const root=document.documentElement;
  if(root && root.dataset) root.dataset.theme = light ? 'light' : 'dark';
  const b=document.getElementById('theme');
  if(b) b.textContent = light ? '☀️ 日间模式' : '🌙 夜间模式';
  if(NH.WAVE && typeof drawWave==='function') drawWave();
  if(typeof paintTicks==='function') paintTicks();
  if(typeof paintTransport==='function') paintTransport();
  if(persist){
    api('/api/theme',{theme:light?'light':'dark'}).then(r=>{
      if(r && r.ok===false) done(r.error||'主题保存失败');
      else if(r && r.warning) done(r.warning);
    }).catch(e=>done('主题保存失败：'+e.message));
  }
}
const initialTheme=(CFG.player&&CFG.player.ui&&CFG.player.ui.theme)==='light'?'light':'dark';
applyTheme(initialTheme,false);
const dataBtn=document.getElementById('datadir');
if(dataBtn) dataBtn.onclick=async()=>{
  const a=window.pywebview && window.pywebview.api;
  if(!a || !a.open_data_dir){ done('仅桌面版支持打开数据目录'); return; }
  try{
    const r=await a.open_data_dir();
    if(r && r.ok===false){ done(r.error||'打开数据目录失败'); return; }
    toast('已打开数据目录');
  }catch(e){ done('打开数据目录失败：'+e.message); }
};
const backPlayingBtn=document.getElementById('backplaying');
if(backPlayingBtn) backPlayingBtn.onclick=()=>{
  if(NH.PLAYING_UID!==null && NH.PLAYING_UID!==undefined)
    load(NH.PLAYING_UID,false);
};
const themeBtn=document.getElementById('theme');
if(themeBtn) themeBtn.onclick=()=>{
  const cur=document.documentElement && document.documentElement.dataset
    ? document.documentElement.dataset.theme : 'dark';
  applyTheme(cur==='light'?'dark':'light',true);
};

async function prepareShutdown(){
  let ok=true;
  try{
    if(NH.VIEW_MODE==='lrc' && NH.flushLrc) ok=await NH.flushLrc();
    if(ok && NH.EDIRTY) ok=false;
    if(ok && NH.saveOpen) await NH.saveOpen();
  }catch(e){ ok=false; }
  try{
    if(window.pywebview && window.pywebview.api && window.pywebview.api.shutdown_ready)
      await window.pywebview.api.shutdown_ready(ok);
  }catch(e){}
  return ok;
}
async function prepareBackgroundFlush(){
  try{
    if(NH.LRC_CONFLICT) return false;
    if(NH.VIEW_MODE==='lrc' && NH.flushLrc) return await NH.flushLrc();
  }catch(e){ return false; }
  return true;
}
NH.prepareBackgroundFlush=prepareBackgroundFlush;
NH.prepareShutdown=prepareShutdown;
if(window.__MOMO_CONFIG_WARNING) setTimeout(()=>toast(window.__MOMO_CONFIG_WARNING), 300);
Object.assign(NH, {lyr, CFG, UI, clampStart, waveTime, waveMarker, waveStep, setWaveMarker, viewStart, spanText, updateWaveHint, syncWaveLabels, syncFollow, setWaveSpan, inlineEdit, measureCanvas, fitCanvas, drawWave, fmt, waitJob, loadWave, saveOpen, load, _toastEl, _showToast, _nextToast, toast, clearToast, lock, busy, done, api, reportClientError, themeColor, applyTheme, audioTime, sourceTime});
})();
