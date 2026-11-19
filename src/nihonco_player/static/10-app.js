// 播放器 · 界面与逻辑总入口（按加载顺序共享全局作用域）
// 文件划分（player.html 里按顺序加载）：
//   10-app.js     状态、工具、歌单、载入单曲、右侧面板
//   20-editor.js  LRC 编辑表格（对齐、增删、粘贴、保存）
//   30-playback.js 统一时间语义、自绘播放条、波形跟随、键盘
let S=null, LINES=[], NAV=[], CUR=-1, loop=false, ids=[], MODE='rm', PLAYING=null, EDITMODE=false;
const lyr=document.getElementById('lyr');
let LIB=[], PLS=[], DRAG=null;

// ── 波形与整体偏移 ────────────────────────────────
const CFG=(window.__CFG)||{};
const UI=(CFG.player&&CFG.player.ui)||{};
const VC=(CFG.vocals)||{};
let WAVE=null, VIEW={span:UI.wave_span||5}, OFFSET=0,
    FOLLOW=UI.follow_default!==false, DRAWN=null;
const cv=document.getElementById('wave'), cx=cv.getContext('2d');
if(cv.style) cv.style.height=(UI.wave_height||120)+'px';
const SPAN_MIN=UI.wave_span_min||2, SPAN_MAX=UI.wave_span_max||10;   // 秒

let PAN_START=0;
function clampStart(st, span){
  const dur=(WAVE && WAVE.duration) || 0;
  return Math.max(0, Math.min(Math.max(0, dur-span), st));
}
function viewStart(){
  const dur=(WAVE && WAVE.duration) || 0;
  const span=Math.min(VIEW.span, dur||VIEW.span);
  if(!FOLLOW) return {start:clampStart(PAN_START, span), span};
  let s0=(au.currentTime||0) - span/2;
  s0=Math.max(0, Math.min((dur||0)-span, s0));
  return {start:s0, span};
}

// ── 缩放 / 跳转 / 数值输入 ──────────────────────
const SPAN_LO=SPAN_MIN, SPAN_HI=SPAN_MAX;
function spanText(v){ return (Math.round(v*10)/10).toString().replace(/\.0$/,'')+'s'; }
function updateWaveHint(){
  const h=document.getElementById('wavehint');
  if(!h) return;
  const src = WAVE && WAVE.source==='vocals' ? '人声波形' : '原曲波形';
  h.textContent = WAVE ? `${src} ${fmt(WAVE.duration)} · 窗口 ${spanText(VIEW.span)}` : '';
}
function syncWaveLabels(){
  const z=document.getElementById('zoomval'); if(z) z.textContent=spanText(VIEW.span);
  const b=document.getElementById('jumpback'), f=document.getElementById('jumpfwd');
  if(b) b.textContent='◀ '+spanText(VIEW.span);
  if(f) f.textContent=spanText(VIEW.span)+' ▶';
  updateWaveHint();
}
function syncFollow(){
  const b=document.getElementById('wavefollow');
  if(!b) return;
  b.textContent='跟随：'+(FOLLOW?'开':'关');
  b.classList.toggle('on', FOLLOW);
}
function setWaveSpan(v){
  VIEW.span=Math.max(SPAN_LO, Math.min(SPAN_HI, +v||VIEW.span));
  if(!FOLLOW) PAN_START=clampStart(PAN_START, VIEW.span);
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
let CANVAS_W=0, CANVAS_H=0, CV_W=0;
function measureCanvas(){ CV_W=cv.getBoundingClientRect().width; }
function fitCanvas(){
  // 用缓存宽度：避免每帧 getBoundingClientRect 触发同步布局（换行时最容易卡一下）
  if(!CV_W) measureCanvas();
  const dpr=1;                                            // 波形是细线，1x 足够，合成压力最小
  const w=Math.max(1,Math.round(CV_W*dpr)), h=Math.max(1,Math.round((UI.wave_height||120)*dpr));
  if(w!==CANVAS_W || h!==CANVAS_H){
    cv.width=w; cv.height=h; CANVAS_W=w; CANVAS_H=h;
    cx.setTransform(dpr,0,0,dpr,0,0);
  }
  return CV_W;
}
function drawWave(){
  const h=UI.wave_height||120;
  const w=fitCanvas();
  cx.clearRect(0,0,w,h);                 // 透明底：少写一层全画布填充
  if(!WAVE || !WAVE.peaks){ return; }
  const {start, span}=viewStart();
  DRAWN={start, span};
  const {step, peaks}=WAVE;
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
    const ls = LRCEDIT ? EROWS : LINES;
    cx.strokeStyle='rgba(200,132,63,0.62)';   // 暖橙色，和绿色波形、亮绿播放头区分开
    cx.lineWidth=1; cx.beginPath();
    (ls||[]).forEach(l=>{
      if(!l || l.t==null) return;
      const lt=l.t+OFFSET;
      if(lt<start || lt>start+span) return;
      const lx=Math.round((lt-start)/perPx)+0.5;
      cx.moveTo(lx,0); cx.lineTo(lx,h);
    });
    cx.stroke();
  }
  // 播放头居中
  const x=Math.round(((au.currentTime||0)-start)/perPx);
  cx.strokeStyle='#7fbfa6'; cx.beginPath(); cx.moveTo(x+0.5,0); cx.lineTo(x+0.5,h); cx.stroke();
}
function fmt(t){ const m=Math.floor(t/60), s=Math.round(t%60); return `${m}:${String(s).padStart(2,'0')}`; }

let VSTAT=null, VPOLL=0;
function paintVStatus(){
  const el=document.getElementById('vchip'); if(!el) return;
  if(!VSTAT || VSTAT.state==='none'){ el.hidden=true; return; }
  el.hidden=false;
  if(VSTAT.state==='done'){
    el.textContent = VSTAT.has_vocals ? '有人声' : '纯音乐';
    el.classList.toggle('vdone', true);
    el.classList.toggle('vinst', !VSTAT.has_vocals);
  }else if(VSTAT.state==='failed'){
    el.textContent='人声分离失败';
  }else{
    el.textContent = VSTAT.state==='queued' ? '人声分离：排队' : '人声分离中…';
  }
}
async function ensureVocals(idx){
  try{ await api('/api/vocals',{action:'ensure', idx}); }catch(e){ return null; }
  return pollVocals(idx);
}
async function pollVocals(idx){
  const seq=++VPOLL;
  for(let k=0;k<400;k++){
    if(seq!==VPOLL || !S || String(S.idx)!==String(idx)) return null;
    let st=null;
    try{ st=await api('/api/vocals/'+idx); }catch(e){ return null; }
    VSTAT=st; paintVStatus();
    if(st.state==='done'){
      if(LRCEDIT) loadWave(true);          // 分离完成 → 换成人声波形
      return st;
    }
    if(st.state==='failed') return st;
    await new Promise(r=>setTimeout(r,1500));
  }
  return null;
}

async function loadWave(force){
  if(!S) return;
  if(!force && WAVE) return;
  WAVE=null;
  try{
    const src=(VSTAT && VSTAT.state==='done' && VSTAT.has_vocals) ? '?src=vocals' : '';
    const d=await api('/api/wave/'+S.idx+src);
    if(d.error){ document.getElementById('wavehint').textContent='无法生成波形：'+d.error; return; }
    WAVE=d;
    updateWaveHint();
    drawWave();
  }catch(e){ document.getElementById('wavehint').textContent='波形加载失败'; }
}
(function waveLoop(){
  let last=0;
  function tick(ts){
    if(WAVE && LRCEDIT && !au.paused && ts-last>=32){ drawWave(); last=ts; }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
document.getElementById('wavefollow').onclick=e=>{
  FOLLOW=!FOLLOW;
  e.target.textContent='跟随：'+(FOLLOW?'开':'关');
  e.target.classList.toggle('on', FOLLOW);
  if(!FOLLOW){ DRAWN=DRAWN||viewStart(); }   // 关掉时冻结当前窗口
};
cv.addEventListener('contextmenu', e=>e.preventDefault());
// 双指滑动（触控板）/ 滚轮：左右平移窗口（竖向滑动也当横向用）
cv.addEventListener('wheel', e=>{
  if(!WAVE) return;
  e.preventDefault();
  const d=e.deltaX || e.deltaY;
  if(!d) return;
  const v=viewStart(), w=cv.getBoundingClientRect().width || 1;
  if(FOLLOW){ FOLLOW=false; syncFollow(); }      // 手动平移 → 关闭跟随
  PAN_START=clampStart(v.start + d*v.span/w, v.span);
  drawWave();
}, {passive:false});
cv.addEventListener('click', e=>{
  if(!WAVE || e.button===2) return;
  const r=cv.getBoundingClientRect();
  const ratio=Math.max(0, Math.min(1,(e.clientX-r.left)/r.width));
  const v=DRAWN || viewStart();                 // 所见即所得
  const t=Math.round((v.start + ratio*v.span)*100)/100;
  seekPrecise(t);
  MARK=Math.round(t*100)/100;
  drawWave();
  const el=document.getElementById('mark');
  el.textContent='标记：'+lrcFmt(MARK); el.classList.add('set');
  drawWave();
});
window.addEventListener('resize', ()=>{ measureCanvas(); drawWave(); });

document.getElementById('zoomout').onclick=()=>setWaveSpan(VIEW.span-1);
document.getElementById('zoomin').onclick=()=>setWaveSpan(VIEW.span+1);
document.getElementById('zoomval').onclick=()=>{
  inlineEdit(document.getElementById('zoomval'), VIEW.span,
    {min:SPAN_LO, max:SPAN_HI, fmt:v=>String(v), apply:v=>setWaveSpan(v)});
};
document.querySelectorAll('#wavebar [data-seek]').forEach(b=>b.onclick=()=>{
  seekPrecise(Math.max(0, Math.min(au.duration||0, au.currentTime + parseFloat(b.dataset.seek))));
});
document.getElementById('jumpback').onclick=()=>{
  seekPrecise(Math.max(0, au.currentTime - VIEW.span));
};
document.getElementById('jumpfwd').onclick=()=>{
  seekPrecise(Math.min(au.duration||0, au.currentTime + VIEW.span));
};
document.querySelectorAll('.off button').forEach(b=>b.onclick=async()=>{
  if(!S) return;
  OFFSET=Math.round((OFFSET+parseFloat(b.dataset.off))*100)/100;
  S.offset=OFFSET;
  document.getElementById('offval').textContent=OFFSET.toFixed(2)+'s';
  syncModes(); drawWave();
  const i=idxAt(au.currentTime);
  if(i>=0) highlight(i);
  await api('/api/pl',{action:'ui_offset', idx:S.idx, offset:OFFSET});
});
document.getElementById('offval').onclick=()=>{
  if(!LRCEDIT || LRC_LOCKED) return;
  const el=document.getElementById('offval');
  inlineEdit(el, OFFSET, {min:-10, max:10, fmt:v=>v.toFixed(2), apply:async v=>{
    OFFSET=Math.round(v*100)/100;
    if(S) S.offset=OFFSET;
    el.textContent=OFFSET.toFixed(2)+'s';
    syncModes(); drawWave();
    const i=idxAt(au.currentTime); if(i>=0) highlight(i);
    if(S) await api('/api/pl',{action:'ui_offset', idx:S.idx, offset:OFFSET});
  }});
};

let OPEN=new Set();
function saveOpen(){
  fetch('/api/pl',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'ui_open', ids:[...OPEN]})});
}

let LOAD_REQUEST=0;
async function load(i, autoplay, nextEditMode){
  if(LRC_REPLACING) return false;
  const request=++LOAD_REQUEST;
  const editing=LRCEDIT;
  let d;
  try{
    if(editing){
      setLrcLocked(true);
      if(!await flushLrc()) return false;
      if(request!==LOAD_REQUEST) return false;
    }
    d=await api('/api/song/'+i);
    if(request!==LOAD_REQUEST) return false;
  }catch(e){
    if(request===LOAD_REQUEST) done('加载歌曲失败：'+e.message);
    return false;
  }finally{
    if(editing && request===LOAD_REQUEST) setLrcLocked(false);
  }
  const changedSong=!S || String(S.idx)!==String(d.idx);
  if(changedSong || nextEditMode!==undefined){
    EDITMODE=nextEditMode===true;
    LRCEDIT=false;
    syncModes();
  }
  if(d.pending){                               // 没有歌词 → 先能播，再后台匹配
    S=d; LINES=[]; CUR=-1; NAV=[];
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML='<div class="lm">匹配歌词中…</div>';
    busy('匹配歌词中…');
    document.getElementById('rmcol').innerHTML='';
    commitAudio();                             // 没有歌词也要能播放
    au.playbackRate=+document.getElementById('rate').value;
    if(autoplay) au.play().catch(()=>{});
    lyr.innerHTML='<div class="lm">分离人声，确认是否有人声…</div>';
    const v=(VC.auto_start===false) ? null : await ensureVocals(d.idx);
    if(request!==LOAD_REQUEST) return false;
    if(v && v.state==='done' && v.has_vocals===false){
      lyr.innerHTML='<div class="lm">纯音乐（无人声），不匹配歌词</div>';
      done('这首是纯音乐，跳过歌词匹配');
      return true;
    }
    try{
      await api('/api/pl',{action:'match',idx:d.idx});
      for(let k=0;k<40 && request===LOAD_REQUEST;k++){
        await new Promise(r=>setTimeout(r,1500));
        if(request!==LOAD_REQUEST) return false;
        const d2=await api('/api/song/'+i);
        if(request!==LOAD_REQUEST) return false;
        if(!d2.pending) return load(i, autoplay, nextEditMode);
      }
    }catch(e){
      if(request!==LOAD_REQUEST) return false;
    }
    if(request!==LOAD_REQUEST) return false;
    lyr.innerHTML='<div class="lm">没匹配到歌词（仍可播放）</div>';
    done('这首歌没匹配到歌词，仍可播放');
    return true;
  }
  {
    S=d; LINES=d.lines; CUR=-1;
    if(String(PLAYING) !== String(d.idx)){
      document.querySelectorAll('.ln.on,.ln2.on').forEach(el=>el.classList.remove('on'));
    }
    NAV=LINES.map((l,i)=>l.meta?-1:i).filter(i=>i>=0);
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML=LINES.map((l,n)=>`<div class="ln" data-n="${n}"><span class="tx">${String(n+1).padStart(2,'0')}</span> ${l.ruby}</div>`).join('');
    document.querySelectorAll('.ln').forEach(el=>el.onclick=()=>seek(+el.dataset.n));
    renderSide();
    restoreEdits();
    OFFSET = d.offset || 0;
    document.getElementById('offval').textContent = OFFSET.toFixed(2)+'s';
    syncModes();
    if(LRCEDIT) renderLrcTable();
    else WAVE=null;
    if(PLAYING===null) commitAudio();                 // 第一次载入才绑定音频

    if(autoplay){ commitAudio(); au.play().catch(()=>{}); }
    au.playbackRate=+document.getElementById('rate').value;
  }
  VSTAT=null; paintVStatus();
  if(!LRCEDIT) WAVE=null;
  if(VC.auto_start!==false) ensureVocals(d.idx);
  return true;
}
function navIdx(n){ const k=NAV.indexOf(n); return k<0?0:k; }

function toast(msg, ms=(UI.toast_ms||4200)){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; document.body.appendChild(t); }
  t.textContent=msg; t.classList.add('on');
  clearTimeout(t._h);
  if(ms>0) t._h=setTimeout(()=>t.classList.remove('on'), ms);
}
let BUSY=false;
function lock(btn, on){
  BUSY=on;
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
  if(!r.ok) throw new Error((await r.text())||('HTTP '+r.status));
  return r.json();
}

async function loadLib(){
  const d = await api('/api/pl');
  PLS = d.lists || d;
  if(d.open && d.open.length) OPEN = new Set(d.open);
  LIB = PLS.flatMap(g=>g.items);
  renderList();
}

function renderList(){
  const q=(document.getElementById('q').value||'').trim().toLowerCase();
  const hit=x=>!q || (x.orig||'').toLowerCase().includes(q) || (x.title||'').toLowerCase().includes(q)
                 || (x.artist||'').toLowerCase().includes(q);
  let html='';
  PLS.forEach(g=>{
    const its=g.items.filter(hit);
    if(q && !its.length) return;
    const open=q || OPEN.has(g.id);
    html+=`<div class="pl" data-id="${g.id}">
      <div class="plh" draggable="true" data-act="toggle" data-id="${g.id}" title="右键：导入 / 重命名 / 清空 / 删除">
        <span class="car">${open?'▾':'▸'}</span><span class="pln">${g.name}</span>
        <span class="plc">${its.length}</span></div>
      <div class="plb" ${open?'':'hidden'}>`
      + its.map(x=>`<div class="it" data-i="${x.idx}" data-u="${x.uid}" data-hl="${x.has_lyric===false?0:1}" draggable="true">
          <div class="t1"><span class="orig">${x.orig||x.title}</span>
            ${(x.orig||'')===(x.title||'')?'':`<span class="mch">${x.title}</span>`}</div>
          <div class="ar">${x.artist}</div>
          <b class="del" data-act="del-entry" data-u="${x.uid}" data-id="${g.id}" title="从歌单移除">✕</b>
        </div>`).join('')
      + `</div></div>`;
  });
  document.getElementById('list').innerHTML=html||'<div class="empty">没有歌</div>';
}

// 歌单右键菜单：导入 / 重命名 / 清空 / 删除
function closeCtx(){ document.getElementById('ctxmenu')?.remove(); }
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
    const name=prompt('新的歌单名', g.name);
    if(!name || name===g.name) return;
    await api('/api/pl',{action:'list_rename',id:g.id,name});
    loadLib();
  });
  mk('清空歌单', async ()=>{
    if(!confirm(`清空「${g.name}」？歌本身不会丢`)) return;
    await api('/api/pl',{action:'list_clear',id:g.id});
    loadLib();
  });
  if(!g.locked) mk('删除歌单', async ()=>{
    if(!confirm(`删除歌单「${g.name}」？（歌本身不会丢）`)) return;
    await api('/api/pl',{action:'list_delete',id:g.id});
    loadLib();
  }, true);
  document.body.appendChild(box);
  const r=box.getBoundingClientRect();
  box.style.left=Math.min(x, window.innerWidth-r.width-8)+'px';
  box.style.top=Math.min(y, window.innerHeight-r.height-8)+'px';
}
document.getElementById('list').addEventListener('contextmenu', e=>{
  const h=e.target.closest('.plh');
  if(!h) return;
  e.preventDefault();
  const g=PLS.find(x=>x.id===h.dataset.id);
  if(g) openPlMenu(e.clientX, e.clientY, g);
});
document.addEventListener('click', closeCtx);
document.addEventListener('keydown', e=>{
  if(e.key==='Escape') closeCtx(); });

// 一次事件委托，避免重复绑定
document.getElementById('list').addEventListener('click', async e=>{
  const delEntry=e.target.closest('[data-act="del-entry"]');
  if(delEntry){ e.stopPropagation();
    await api('/api/pl',{action:'entry_remove',uid:delEntry.dataset.u,from:delEntry.dataset.id});
    return loadLib(); }

  const head=e.target.closest('[data-act="toggle"]');
  if(head){ const id=head.dataset.id;
    OPEN.has(id)?OPEN.delete(id):OPEN.add(id); saveOpen(); return renderList(); }

  const row=e.target.closest('.it');
  if(row){ document.querySelectorAll('.it').forEach(x=>x.style.background='');
    row.style.background='#182430'; load(row.dataset.i); }
});
document.getElementById('list').addEventListener('dblclick', e=>{
  const row=e.target.closest('.it');
  if(row) load(row.dataset.i, true);
});
document.getElementById('list').addEventListener('dragstart', e=>{
  const row=e.target.closest('.it'), head=e.target.closest('.plh');
  if(row){ const pl=row.closest('.pl');
    DRAG={kind:'song', uid:row.dataset.u, from:pl.dataset.id};
    e.dataTransfer.setData('text/plain','song'); }
  else if(head){ const pl=head.parentElement;
    if(pl.dataset.id==='default'){ DRAG=null; return; }   // 默认歌单固定置顶
    DRAG={kind:'list', id:pl.dataset.id};
    e.dataTransfer.setData('text/plain','list'); }
});
document.getElementById('list').addEventListener('dragover', e=>{
  if(e.target.closest('.it')||e.target.closest('.plh')||e.target.closest('.plb')) e.preventDefault();
});
document.getElementById('list').addEventListener('drop', async e=>{
  if(!DRAG) return;
  const targetRow=e.target.closest('.it');
  const targetPl=(e.target.closest('.pl')||{}).dataset;
  const toPl=targetPl && targetPl.id;
  if(DRAG.kind==='song'){
    if(!toPl) return;
    if(targetRow){                                   // 落在某首歌上 → 插到它前面
      const uids=[...e.target.closest('.plb').querySelectorAll('.it')].map(x=>x.dataset.u);
      if(DRAG.from===toPl){
        const arr=uids.filter(u=>u!==DRAG.uid);
        arr.splice(arr.indexOf(targetRow.dataset.u), 0, DRAG.uid);
        await api('/api/pl',{action:'entry_reorder',list:toPl,uids:arr});
      }else{
        await api('/api/pl',{action:'entry_move',from:DRAG.from,to:toPl,uid:DRAG.uid});
      }
    }else{                                           // 落在歌单空白处 → 移过去
      if(DRAG.from!==toPl) await api('/api/pl',{action:'entry_move',from:DRAG.from,to:toPl,uid:DRAG.uid});
    }
  }else if(DRAG.kind==='list' && toPl && DRAG.id!==toPl){
    const ids=[...document.querySelectorAll('.pl')].map(x=>x.dataset.id).filter(x=>x!=='default');
    ids.splice(ids.indexOf(DRAG.id),1);
    ids.splice(ids.indexOf(toPl),0,DRAG.id);
    await api('/api/pl',{action:'list_reorder',ids});
  }
  DRAG=null; loadLib();
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
    paths = (prompt('路径（多个用 ; 分隔）')||'').split(';').map(x=>x.trim()).filter(Boolean);
  }
  if(!paths.length) return;
  busy('导入中…');
  try{
    const r = await api('/api/pl',{action:'import', list:listId, paths});
    if(r.lists) PLS=r.lists; LIB=PLS.flatMap(g=>g.items); renderList();
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

document.getElementById('newlist').onclick=async()=>{
  const name=prompt('新歌单名称'); if(!name) return;
  await api('/api/pl',{action:'list_create',name}); loadLib();
};
loadLib().catch(async()=>{            // 启动偶发失败 → 延迟重试一次
  await new Promise(r=>setTimeout(r,600));
  loadLib().catch(e=>toast('加载歌单失败：'+e.message));
});

document.getElementById('resetall').onclick=async()=>{
  if(!S) return;
  await api('/api/pl',{action:'edit_clear', idx:S.idx});
  toast('已恢复默认标注');
  load(S.idx);
};
