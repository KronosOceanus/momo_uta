let S=null, LINES=[], NAV=[], CUR=-1, loop=false, ids=[], MODE='rm', PLAYING=null, EDITMODE=false;
const au=document.getElementById('au'), lyr=document.getElementById('lyr');
let LIB=[], PLS=[], DRAG=null;

// ── 波形与整体偏移 ────────────────────────────────
let WAVE=null, VIEW={start:0, span:0}, OFFSET=0;
const cv=document.getElementById('wave'), cx=cv.getContext('2d');

function fitCanvas(){
  const r=cv.getBoundingClientRect();
  const dpr=window.devicePixelRatio||1;
  cv.width=Math.max(1,Math.round(r.width*dpr));
  cv.height=Math.max(1,Math.round(r.height*dpr));
  cx.setTransform(dpr,0,0,dpr,0,0);
  return r.width;
}
function drawWave(){
  const w=fitCanvas(), h=120;
  cx.clearRect(0,0,w,h);
  const mid=h/2;
  cx.fillStyle='#1a2029'; cx.fillRect(0,0,w,h);
  if(!WAVE || !WAVE.peaks){ return; }
  const {step, peaks}=WAVE;
  const span=VIEW.span || WAVE.duration || 1;
  const start=VIEW.start;
  const perPx=span/w;
  const i0=Math.max(0, Math.floor(start/step)), i1=Math.min(peaks.length, Math.ceil((start+span)/step));
  cx.strokeStyle='#4a7f6b'; cx.beginPath();
  for(let i=i0;i<i1;i++){
    const t=i*step;
    const x=Math.round((t-start)/perPx);
    const [mn,mx]=peaks[i];
    cx.moveTo(x+0.5, mid-mx*mid*0.95);
    cx.lineTo(x+0.5, mid-mn*mid*0.95);
  }
  cx.stroke();
  // 播放头
  const ct=au.currentTime||0;
  if(ct>=start && ct<=start+span){
    const x=Math.round((ct-start)/perPx);
    cx.strokeStyle='#7fbfa6'; cx.beginPath(); cx.moveTo(x+0.5,0); cx.lineTo(x+0.5,h); cx.stroke();
  }
  // 时间刻度
  cx.fillStyle='#5b626c'; cx.font='11px ui-monospace, monospace';
  const tick=span>30?10:span>10?5:1;
  for(let t=Math.ceil(start/tick)*tick; t<=start+span; t+=tick){
    const x=(t-start)/perPx;
    cx.fillText(fmt(t), x+4, 12);
  }
}
function fmt(t){ const m=Math.floor(t/60), s=Math.round(t%60); return `${m}:${String(s).padStart(2,'0')}`; }

async function loadWave(){
  if(!S) return;
  WAVE=null; VIEW={start:0, span:0};
  try{
    const d=await api('/api/wave/'+S.idx);
    if(d.error){ document.getElementById('wavehint').textContent='无法生成波形：'+d.error; return; }
    WAVE=d; VIEW={start:0, span:Math.min(d.duration, 30)};
    document.getElementById('wavehint').textContent=
      `波形 ${fmt(d.duration)} · 滚轮缩放 · 点击定位` + (S.offset?` · 偏移 ${S.offset.toFixed(2)}s`:'');
    drawWave();
  }catch(e){ document.getElementById('wavehint').textContent='波形加载失败'; }
}
cv.addEventListener('click', e=>{
  if(!WAVE) return;
  const r=cv.getBoundingClientRect();
  const ratio=(e.clientX-r.left)/r.width;
  const t=VIEW.start + ratio*VIEW.span;
  au.currentTime=t;
  MARK=Math.round(t*100)/100;
  const el=document.getElementById('mark');
  el.textContent='标记：'+lrcFmt(MARK); el.classList.add('set');
  drawWave();
});
cv.addEventListener('wheel', e=>{
  if(!WAVE) return;
  e.preventDefault();
  const r=cv.getBoundingClientRect();
  const ratio=(e.clientX-r.left)/r.width;
  const anchor=VIEW.start+ratio*VIEW.span;
  VIEW.span=Math.min(WAVE.duration, Math.max(1, VIEW.span*(e.deltaY>0?1.25:0.8)));
  VIEW.start=Math.max(0, Math.min(WAVE.duration-VIEW.span, anchor-ratio*VIEW.span));
  drawWave();
}, {passive:false});
window.addEventListener('resize', ()=>drawWave());

document.querySelectorAll('.off button').forEach(b=>b.onclick=async()=>{
  if(!S) return;
  OFFSET=Math.round((OFFSET+parseFloat(b.dataset.off))*100)/100;
  S.offset=OFFSET;
  document.getElementById('offval').textContent=OFFSET.toFixed(2)+'s';
  syncModes(); drawWave();
  await api('/api/pl',{action:'ui_offset', idx:S.idx, offset:OFFSET});
});
setInterval(()=>{ if(WAVE) drawWave(); }, 120);

let OPEN=new Set();
function saveOpen(){
  fetch('/api/pl',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'ui_open', ids:[...OPEN]})});
}

async function load(i, autoplay){
  const prevIdx = S ? String(S.idx) : null;
  const d = await (await fetch('/api/song/'+i)).json();
  if(prevIdx !== String(d.idx)){        // 换歌 → 两个编辑模式都关掉
    EDITMODE=false; LRCEDIT=false;
    if(typeof syncModes==='function') syncModes();
  }
  if(d.pending){                               // 没有歌词 → 懒匹配
    S=d; LINES=[]; CUR=-1;
    document.getElementById('vtitle').textContent=d.title+(d.artist?' · '+d.artist:'');
    lyr.innerHTML='<div class="lm">匹配歌词中…</div>';
    busy('匹配歌词中…');
    document.getElementById('rmcol').innerHTML='';
    await fetch('/api/pl',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'match',idx:d.idx})});
    for(let k=0;k<40;k++){
      await new Promise(r=>setTimeout(r,1500));
      const d2 = await (await fetch('/api/song/'+i)).json();
      if(!d2.pending){ return load(i, autoplay); }
    }
    lyr.innerHTML='<div class="lm">没匹配到歌词</div>';
    done('这首歌没匹配到歌词');
    return;
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
    if(LRCEDIT) loadWave(); else { WAVE=null; }
    if(PLAYING===null) commitAudio();                 // 第一次载入才绑定音频

    if(autoplay){ commitAudio(); au.play().catch(()=>{}); }
    au.playbackRate=+document.getElementById('rate').value;
  }
}
function navIdx(n){ const k=NAV.indexOf(n); return k<0?0:k; }

function toast(msg, ms=4200){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; document.body.appendChild(t); }
  t.textContent=msg; t.classList.add('on');
  clearTimeout(t._h);
  if(ms>0) t._h=setTimeout(()=>t.classList.remove('on'), ms);
}
let BUSY=false;
function lock(btn, on){
  BUSY=on;
  document.querySelectorAll('.padd,#rem').forEach(b=>{ if(!b) return;
    b.style.pointerEvents = on ? 'none' : '';
    b.style.opacity = on ? '.45' : '';
  });
  if(btn){ btn.disabled=on; }
}

// 进行中：常驻，等 done() 或新的 toast() 覆盖
function busy(msg){ toast(msg, 0); }
// 一次性结果：几秒后自动消失
function done(msg){ toast(msg, 4200); }

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
    const add=`<b class="padd" data-act="add-to" data-id="${g.id}" title="往这个歌单导入">＋</b>`;
    const clr=`<b class="pclear" data-act="clear-list" data-id="${g.id}" title="清空歌单"><svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 4.5h10M6.2 4.5V3.2h3.6v1.3M4.6 4.5l.5 8.3h5.8l.5-8.3" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></b>`;
    const del=g.locked?'':`<b class="pdel" data-act="del-list" data-id="${g.id}" title="删除歌单">✕</b>`;
    html+=`<div class="pl" data-id="${g.id}">
      <div class="plh" draggable="true" data-act="toggle" data-id="${g.id}">
        <span class="car">${open?'▾':'▸'}</span><span class="pln">${g.name}</span>
        <span class="plc">${its.length}</span>${add}${clr}${del}</div>
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

// 一次事件委托，避免重复绑定
document.getElementById('list').addEventListener('click', async e=>{
  const addBtn=e.target.closest('[data-act="add-to"]');
  if(addBtn){ e.stopPropagation(); return doImport(addBtn.dataset.id, addBtn); }

  const clearList=e.target.closest('[data-act="clear-list"]');
  if(clearList){ e.stopPropagation();
    if(!confirm('清空「默认歌单」？歌本身不会丢')) return;
    await api('/api/pl',{action:'list_clear',id:clearList.dataset.id}); return loadLib(); }

  const delList=e.target.closest('[data-act="del-list"]');
  if(delList){ e.stopPropagation();
    if(!confirm('删除这个歌单？（歌本身不会丢）')) return;
    await api('/api/pl',{action:'list_delete',id:delList.dataset.id}); return loadLib(); }

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
let LRCEDIT=false;

// ── LRC 编辑表格 ────────────────────────────────
let EROWS=[], ESEL=-1, SEL=new Set(), MARK=null, EDIRTY=false, UNDO=[], REDO=[];

function snapshot(){
  UNDO.push(JSON.stringify(EROWS)); if(UNDO.length>50) UNDO.shift();
  REDO=[]; EDIRTY=true;
}
function undo(){
  if(!UNDO.length) return;
  REDO.push(JSON.stringify(EROWS));
  EROWS=JSON.parse(UNDO.pop()); ESEL=Math.min(ESEL, EROWS.length-1);
  SEL.clear(); renderLrcTable();
}
function redo(){
  if(!REDO.length) return;
  UNDO.push(JSON.stringify(EROWS));
  EROWS=JSON.parse(REDO.pop()); SEL.clear(); renderLrcTable();
}

function lrcFmt(t){ if(t===null||t===undefined) return '';
  const m=Math.floor(t/60), s=(t-m*60);
  return `${String(m).padStart(2,'0')}:${s.toFixed(2).padStart(5,'0')}`; }
function lrcParse(v){
  const m=/^(\d+):(\d+(?:\.\d+)?)$/.exec((v||'').trim()); if(!m) return null;
  return Math.round((+m[1]*60 + +m[2])*100)/100;
}
function lrcText(){
  return EROWS.map(r=>`[${lrcFmt(r.t)||'00:00.00'}]${r.text||''}`).join('\n')+'\n';
}

async function openLrcEditor(){
  const d=await api('/api/lrc',{action:'load', idx:S.idx});
  const fileRows=(d.lines||[]).map(x=>({t:x.t, text:x.text}));
  // 优先用 .lrc 文件；行数不一致时改用"当前播放列表"的行，保证左右对齐
  let base, note='';
  if(fileRows.length && fileRows.length===LINES.length){
    base=fileRows;
  }else if(LINES.length){
    base=LINES.map(l=>({t:(l.meta?l.t:l.t), text:l.text}));
    if(fileRows.length) note='（.lrc 与播放列表行数不同，按播放列表对齐）';
  }else{
    base=fileRows;
  }
  EROWS=base;
  if(!EROWS.length) EROWS=[{t:null,text:''}];
  if(note) done('已加载'+note);
  ESEL=0; SEL.clear(); EDIRTY=false; MARK=null;
  renderLrcTable();
}

function rowHtml(r,i){
  return `<div class="lerow${i===ESEL?' sel':''}${SEL.has(i)?' picked':''}" data-i="${i}">
    <span class="no">${String(i+1).padStart(2,'0')}</span>
    <input class="ts${r.t===null?' none':''}" data-i="${i}" value="${r.t===null?'':lrcFmt(r.t)}" placeholder="mm:ss.xx">
    <span class="bind" data-i="${i}" title="把标记时间写进这一行">↤</span>
    <input class="tx" data-i="${i}" value="${(r.text||'').replace(/"/g,'&quot;')}">
    <span class="del" data-i="${i}" title="删除这一行">✕</span>
  </div>`;
}

function renderLrcTable(){
  const box=document.getElementById('lyr');
  box.innerHTML='<div class="letable">'+EROWS.map(rowHtml).join('')+'</div>';
  const rows=box.querySelectorAll('.lerow');

  rows.forEach(el=>{
    el.onclick=e=>{
      if(e.target.tagName==='INPUT') return;      // 输入框内点击：不抢焦点
      const i=+el.dataset.i;
      if(e.metaKey||e.ctrlKey){ SEL.has(i)?SEL.delete(i):SEL.add(i); }
      else if(e.shiftKey && ESEL>=0){ SEL.clear();
        for(let k=Math.min(ESEL,i);k<=Math.max(ESEL,i);k++) SEL.add(k); }
      else { SEL.clear(); }
      ESEL=i; paintSelection();
      const r=EROWS[i];
      if(r && r.t!==null) seekIdx(i, true);
    };
  });
  box.querySelectorAll('input.ts').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onchange=()=>{
      const i=+el.dataset.i, v=el.value.trim();
      if(!v){ snapshot(); EROWS[i].t=null; renderLrcTable(); return; }
      const t=lrcParse(v);
      if(t===null){ done('时间戳格式应为 mm:ss.xx'); el.value=lrcFmt(EROWS[i].t); return; }
      snapshot(); EROWS[i].t=t; renderLrcTable();
    };
    el.onkeydown=ev=>{ if(ev.isComposing||ev.keyCode===229) return;
      if(ev.key==='Enter'){ ev.preventDefault(); el.blur(); } };
  });
  box.querySelectorAll('input.tx').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onfocus=()=>{ ESEL=+el.dataset.i; paintSelection(); };
    el.oninput=()=>{ EROWS[+el.dataset.i].text=el.value; EDIRTY=true; };
    el.onkeydown=ev=>{
      if(ev.isComposing||ev.keyCode===229) return;
      if(ev.key==='Enter'){
        ev.preventDefault();
        const i=+el.dataset.i, pos=el.selectionStart, v=el.value;
        const left=v.slice(0,pos), right=v.slice(pos);
        snapshot();
        EROWS[i].text=left;
        EROWS.splice(i+1, 0, {t:null, text:right});
        ESEL=i+1; SEL.clear(); EDIRTY=true;
        renderLrcTable();
        const nx=document.querySelector(`.lerow[data-i="${i+1}"] input.tx`);
        if(nx){ nx.focus(); nx.setSelectionRange(0,0); }
        document.querySelector(`.lerow[data-i="${i+1}"]`)?.scrollIntoView({block:'center'});
      }
    };
    el.onpaste=ev=>{
      const text=(ev.clipboardData||window.clipboardData).getData('text');
      if(!text || !text.includes('\n')) return;      // 单行正常粘贴
      ev.preventDefault();
      const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(x=>x!=='');
      if(!lines.length) return;
      snapshot();
      const at=Math.max(0,+el.dataset.i+1);
      const fresh=lines.map(x=>{
        const m=/^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/.exec(x);
        return m ? {t:Math.round((+m[1]*60 + +m[2])*100)/100, text:m[3]}
                 : {t:null, text:x};
      });
      EROWS.splice(at,0,...fresh);
      ESEL=at+fresh.length-1; SEL.clear(); renderLrcTable();
      done(`粘贴了 ${fresh.length} 行`);
    };
  });
  box.querySelectorAll('.bind').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); bindMark(+el.dataset.i); };
  });
  box.querySelectorAll('.del').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); snapshot(); EROWS.splice(+el.dataset.i,1);
      if(!EROWS.length) EROWS=[{t:null,text:''}];
      ESEL=Math.min(ESEL,EROWS.length-1); SEL.clear(); renderLrcTable(); };
  });
}

function paintSelection(){
  document.querySelectorAll('.lerow').forEach(el=>{
    const i=+el.dataset.i;
    el.classList.toggle('sel', i===ESEL);
    el.classList.toggle('picked', SEL.has(i));
  });
}
function insertPos(){
  if(SEL.size) return Math.max(...SEL)+1;
  if(ESEL>=0 && ESEL<EROWS.length) return ESEL+1;
  return EROWS.length;
}
function insertLines(text){
  const lines=(text||'').split(/\r?\n/).map(x=>x.trim()).filter(x=>x!=='');
  if(!lines.length) return 0;
  snapshot();
  const at=insertPos();
  const fresh=lines.map(x=>{
    const m=/^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/.exec(x);
    return m ? {t:Math.round((+m[1]*60 + +m[2])*100)/100, text:m[3]}
             : {t:null, text:x};
  });
  EROWS.splice(at,0,...fresh);
  ESEL=at+fresh.length-1; SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${ESEL}"]`)?.scrollIntoView({block:'center'});
  return fresh.length;
}
function addRow(at){
  snapshot();
  const pos = (at===undefined) ? insertPos() : at;
  EROWS.splice(pos,0,{t:null,text:''});
  ESEL=pos; SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${pos}"]`)?.scrollIntoView({block:'center'});
}
function delRows(){
  const idx = SEL.size ? [...SEL] : (ESEL>=0?[ESEL]:[]);
  if(!idx.length) return;
  snapshot();
  idx.sort((a,b)=>b-a).forEach(i=>EROWS.splice(i,1));
  if(!EROWS.length) EROWS=[{t:null,text:''}];
  ESEL=Math.min(idx[idx.length-1],EROWS.length-1); SEL.clear(); renderLrcTable();
}
function selectAll(){
  SEL.clear(); for(let i=0;i<EROWS.length;i++) SEL.add(i);
  renderLrcTable(); done(`已选中 ${EROWS.length} 行`);
}
function bindMark(i){
  if(MARK===null){ done('先在波形上点一个位置'); return; }
  snapshot(); EROWS[i].t=MARK;
  ESEL=Math.min(EROWS.length-1, i+1); SEL.clear();
  renderLrcTable();
  document.querySelector(`.lerow[data-i="${ESEL}"]`)?.scrollIntoView({block:'center'});
}

document.addEventListener('paste', e=>{
  if(!LRCEDIT) return;
  if(e.target && e.target.tagName==='INPUT') return;   // 输入框里走原生粘贴
  const text=(e.clipboardData||window.clipboardData||{}).getData
    ? (e.clipboardData||window.clipboardData).getData('text') : '';
  if(!text) return;
  e.preventDefault();
  const n=insertLines(text);
  if(n) done(`粘贴了 ${n} 行`);
});
document.getElementById('lrcpaste').onclick=()=>{
  if(!LRCEDIT) return;
  const wrap=document.createElement('div'); wrap.className='pastewrap';
  wrap.innerHTML=`<div class="pastebox">
    <h3>粘贴歌词（每行一句，支持 [mm:ss.xx] 前缀；插入到选中行下面）</h3>
    <textarea id="pastearea" placeholder="把歌词粘贴到这里…"></textarea>
    <div class="row"><button id="pastecancel">取消</button>
      <button id="pasteok" class="primary">插入</button></div></div>`;
  document.body.appendChild(wrap);
  const ta=wrap.querySelector('#pastearea'); ta.focus();

  const close=()=>wrap.remove();
  wrap.querySelector('#pastecancel').onclick=close;
  wrap.addEventListener('click',e=>{ if(e.target===wrap) close(); });
  wrap.querySelector('#pasteok').onclick=()=>{
    const text=ta.value||'';
    const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(x=>x!=='');
    const n=insertLines(ta.value);
    close();
    n ? done(`插入 ${n} 行`) : done('没粘贴到内容');
  };
};
document.getElementById('lrcadd').onclick=()=>{ if(LRCEDIT) addRow(); };
document.getElementById('lrcdel').onclick=()=>{ if(LRCEDIT) delRows(); };
document.getElementById('lrcselall').onclick=()=>{ if(LRCEDIT) selectAll(); };
document.getElementById('lrcsaveas').onclick=async()=>{
  if(!LRCEDIT) return;
  const name=(S&&S.title?S.title:'lyrics')+'.lrc';
  const text=lrcText();
  if(window.pywebview && window.pywebview.api && window.pywebview.api.save_text){
    const p=await window.pywebview.api.save_text(name, text);
    done(p ? '已另存为 '+p.split('/').pop() : '已取消');
  }else done('当前环境不支持另存为');
};
document.getElementById('lrcreset').onclick=async()=>{
  if(!LRCEDIT || !S) return;
  const st=await api('/api/lrc',{action:'backup', idx:S.idx});
  if(!st.exists){ done('没有备份（首次保存时才会生成）'); return; }
  const when=new Date(st.mtime*1000).toLocaleString();
  if(!confirm(`恢复到这个备份？\n${when} · ${st.lines} 行\n当前编辑内容会丢失`)) return;
  busy('恢复中…');
  const r=await api('/api/lrc',{action:'restore', idx:S.idx});
  if(!r.ok){ done(r.error||'恢复失败'); return; }
  done(`已恢复最初版本（${r.lines} 行）`);
  await openLrcEditor();
};
document.getElementById('lrcsave').onclick=async()=>{
  if(!LRCEDIT) return;
  if(!EROWS.length){ done('没有歌词行'); return; }
  const back=EROWS.some((r,i)=>i>0 && r.t!==null && EROWS.slice(0,i).some(p=>p.t!==null && r.t<p.t));
  if(back && !confirm('有时间戳倒退的行，仍然保存？')) return;
  const unaligned=EROWS.filter(r=>r.t===null).length;
  if(unaligned && !confirm(`有 ${unaligned} 行还没对齐时间，仍然保存？`)) return;
  busy('保存中…');
  try{
    const r=await api('/api/lrc',{action:'save', idx:S.idx,
      lines:EROWS.map(x=>({t:x.t, text:x.text}))});
    if(!r.ok){ done(r.error||'保存失败'); return; }
    EDIRTY=false;
    done(`已保存 ${r.lines} 行${r.backed_up?'（已备份原文件）':''}`);
  }catch(e){ done('保存失败：'+e.message); }
};

document.addEventListener('keydown', e=>{
  if(!LRCEDIT) return;
  const ins=e.target.tagName==='INPUT';
  if(ins) return;                       // 输入框里的 Enter 走"拆行"
  if(e.key==='Enter'){ e.preventDefault(); addRow(); return; }
  if((e.metaKey||e.ctrlKey) && (e.key==='a'||e.key==='A')){ e.preventDefault(); selectAll(); return; }
  if(e.key==='Delete'||e.key==='Backspace'){ e.preventDefault(); delRows(); return; }
  if((e.metaKey||e.ctrlKey) && (e.key==='z'||e.key==='Z')){ e.preventDefault(); e.shiftKey?redo():undo(); }
});

function syncModes(){
  const e=document.getElementById('edit'), l=document.getElementById('lrcedit');
  const body=document.body;
  body.classList.toggle('fak', EDITMODE);
  body.classList.toggle('lrcedit', LRCEDIT);

  e.textContent='振假名编辑模式：'+(EDITMODE?'开':'关');
  l.textContent='LRC 编辑模式：'+(LRCEDIT?'开':'关');
  e.classList.toggle('on', EDITMODE);
  l.classList.toggle('on', LRCEDIT);

  e.title='编辑读音';
  l.title='编辑歌词时间轴';

  const chip=document.getElementById('offchip');
  if(Math.abs(OFFSET)>0.001){
    chip.hidden=false; chip.textContent='偏移 '+(OFFSET>0?'+':'')+OFFSET.toFixed(2)+'s';
  }else chip.hidden=true;
}

document.getElementById('lrcedit').onclick=()=>{
  LRCEDIT=!LRCEDIT;
  if(LRCEDIT && EDITMODE){ EDITMODE=false; }   // 互斥：开这个就关那个
  syncModes();
  if(LRCEDIT){
    if(S && !WAVE) loadWave();
    if(S) openLrcEditor();
  }else if(S){
    load(S.idx);
  }
};

document.getElementById('offchip').onclick=async()=>{
  OFFSET=0; if(S) S.offset=0;
  document.getElementById('offval').textContent='0.00s';
  syncModes();
  await api('/api/pl',{action:'ui_offset', idx:S?.idx, offset:0});
};

document.getElementById('edit').onclick=()=>{
  EDITMODE=!EDITMODE;
  if(EDITMODE && LRCEDIT){ LRCEDIT=false; }   // 互斥：只切模式，不重载
  syncModes();
};
document.addEventListener('click', async e=>{
  const ew = e.target.closest('.ew');
  if(EDITMODE && ew){
    e.stopPropagation();
    openPicker(ew, [], async v => {
      const lineEl=ew.closest('.ln'); const li=+lineEl.dataset.n; const start=+ew.dataset.start;
      const r=await fetch('/api/line',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({idx:S.idx,line:li,start,reading:v})});
      if(!r.ok) return;
      applyEdit(await r.json());
      flashAt(li, ew.dataset.base);
    });
    return;
  }
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  const bc = e.target.closest('.bc');
  if(!bc) return;
  e.stopPropagation();
  const cands = (bc.dataset.cands||'').split('|').filter(Boolean);
  if(EDITMODE){ openPicker(bc, [], (v)=>{ doEdit(bc, v); }); return; }
  if(cands.length >= 2) openPicker(bc, cands, (v)=>{ doEdit(bc, v); }, false);
});

// 一个弹层：有候选列候选；allowInput 时额外给输入框
function openPicker(el, cands, onPick, allowInput=true){
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  const m = document.createElement('div'); m.className='menu';
  const cur = el.querySelector('rt')?.textContent || '';
  for(const c of cands){
    const b=document.createElement('button'); b.textContent=c;
    if(c===cur) b.classList.add('on');
    b.onclick=ev=>{ev.stopPropagation(); m.remove(); onPick(c);};
    m.appendChild(b);
  }
  let inp=null;
  if(allowInput){
    if(cands.length){ const sep=document.createElement('div'); sep.className='sep'; m.appendChild(sep); }
    inp=document.createElement('input'); inp.placeholder='手动输入'; inp.value=cur; inp.className='kin';
    const ok=document.createElement('button'); ok.textContent='确定';
    const submit=()=>{ const v=inp.value.trim();
      if(!/^[ぁ-んー]+$/.test(v)){ inp.style.borderColor='#c06060'; return; }
      m.remove(); onPick(v); };
    ok.onclick=ev=>{ev.stopPropagation(); submit();};
    inp.onkeydown=ev=>{
      if(ev.isComposing || ev.keyCode===229) return;   // 输入法组词中，别抢 Enter
      if(ev.key==='Enter') submit();
      if(ev.key==='Escape') m.remove();
    };
    const row=document.createElement('div'); row.className='inrow'; row.append(inp, ok);
    m.appendChild(row);
  }
  if(!cands.length && !allowInput) return;
  document.body.appendChild(m);
  const r=el.getBoundingClientRect();
  const bh=m.offsetHeight||200, bw=m.offsetWidth||220;
  let top=r.bottom+4;
  if(top+bh>innerHeight-12) top=Math.max(12, r.top-bh-4);
  m.style.left=Math.max(8, Math.min(r.left, innerWidth-bw-12))+'px';
  m.style.top=top+'px';
  if(inp){ inp.focus(); inp.select(); }
}

async function doEdit(bc, reading){
  const lineEl = bc.closest('.ln'); const li = +lineEl.dataset.n; const start = +bc.dataset.start;
  const r = await fetch('/api/line',{method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx:S.idx, line:li, start, reading})});
  if(!r.ok) return;
  const d = await r.json(); applyEdit(d);
  flashAt(li, bc.dataset.base);
}
function flashAt(li, word){
  const lineEl=document.querySelectorAll('.ln')[li];
  if(lineEl){
    lineEl.querySelectorAll(`[data-base="${word}"]`).forEach(w=>{
      w.classList.add('flash'); setTimeout(()=>w.classList.remove('flash'),1400);});
  }
  const rEl=document.querySelectorAll('.ln2')[li];
  if(rEl){
    let hit=false;
    rEl.querySelectorAll('.w').forEach(w=>{
      if(w.dataset.base===word){ hit=true; w.classList.add('flash');
        setTimeout(()=>w.classList.remove('flash'),1400);} });
    if(!hit){ rEl.classList.add('flash'); setTimeout(()=>rEl.classList.remove('flash'),1400); }
  }
}
function applyEdit(d){
  const el = document.querySelectorAll('.ln')[d.line];
  if(el){ el.innerHTML = `<span class="tx">${String(d.line+1).padStart(2,'0')}</span> ` + d.ruby;
          LINES[d.line].rm = d.rm; LINES[d.line].ky = d.ky; LINES[d.line].ruby = d.ruby;
          if(d.rmH) LINES[d.line].rmH = d.rmH;
          if(d.kyH) LINES[d.line].kyH = d.kyH; }
  renderSide();
}
async function restoreEdits(){
  const store = (S && S.edits) || {};
  const edits = Object.entries(store)
    .map(([k,v])=>{const [l,st]=k.split(':');return {idx:S.idx,line:+l,start:+st,reading:v};})
    .filter(e=>!isNaN(e.line)&&!isNaN(e.start));
  if(!edits.length) return;
  const r = await fetch('/api/apply',{method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx:S.idx, edits})});
  if(!r.ok) return;
  const d = await r.json();
  (d.edits||[]).forEach(applyEdit);
}



function renderSide(){
  const col=document.getElementById('rmcol');
  col.innerHTML=LINES.map((l,n)=>`<div class="ln2" data-n="${n}">
    <span class="tx">${String(n+1).padStart(2,'0')}</span>${(MODE==='rm'?(l.rmH||l.rm):(l.kyH||l.ky))||''}</div>`).join('');
  col.querySelectorAll('.ln2').forEach(el=>el.onclick=()=>{
    const n=+el.dataset.n;
    if(!LINES[n] || isMetaLine(LINES[n])) return;
    seekIdx(LRCEDIT ? rowForTime(LINES[n].t) : n, true);
  });
  if(CUR>=0) paint2(CUR);
}
function syncSideToTime(t){
  if(!LINES.length) return;
  // 取时间最接近的一行（避免边界处偏到下一句）
  let n=-1, best=1e9;
  for(let i=0;i<LINES.length;i++){
    if(isMetaLine(LINES[i])) continue;
    const d=Math.abs(LINES[i].t-t);
    if(d<best){ best=d; n=i; }
  }
  if(n<0) return;
  CUR=n;
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on', i===n && !LINES[i].meta));
  const el=document.querySelectorAll('.ln2')[n];
  if(el) el.scrollIntoView({block:'center', behavior:'smooth'});
}
function paint2(n){
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on',i===n&&!LINES[i].meta));
  const el2=document.querySelectorAll('.ln2')[n];
  if(el2)el2.scrollIntoView({block:'center',behavior:'smooth'});
}
function markPlaying(){
  document.querySelectorAll('.it').forEach(x=>{
    x.dataset.playing = (String(x.dataset.i)===String(PLAYING)) ? '1' : ''; });
}
function commitAudio(){
  if(!S) return;
  PLAYING = S.idx; markPlaying();
  au.src = S.audio;
  document.getElementById('ttl').textContent = '▶ ' + S.title + (S.artist?' · '+S.artist:'');
  syncPlayBtn();
}
// ── 统一播放层：普通视图与编辑表格共用同一套时间语义 ──
const META_RE=/^(作词|作曲|编曲|制作|演唱|歌\s*[:：]|Lyrics|Composer|Arranger|Producer)/;
function viewLines(){ return LRCEDIT ? EROWS : LINES; }
function lineT(l){ return (l && l.t!==null && l.t!==undefined) ? l.t+OFFSET : null; }
function isMetaLine(l){ return !l || l.meta || META_RE.test((l.text||'').trim()); }
function idxAt(t){
  const ls=viewLines(); let n=-1;
  for(let i=0;i<ls.length;i++){ const tt=lineT(ls[i]); if(tt!==null && tt<=t) n=i; }
  return n;
}
function navItems(){
  return viewLines().map((l,i)=>({i, t:lineT(l)})).filter(x=>x.t!==null && !isMetaLine(viewLines()[x.i]));
}
function seekIdx(i, keepPlaying){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  const wasPlaying = keepPlaying!==false && !au.paused;
  if(PLAYING!==S.idx) commitAudio();
  au.currentTime = Math.max(0, lineT(l));
  if(wasPlaying) au.play().catch(()=>{});
  highlight(i);
  if(loop && !isMetaLine(viewLines()[i])) LOOP_ROW=i;
  if(LRCEDIT){ ESEL=i; SEL.clear(); paintSelection(); }
}
function nextIdx(dir){
  const items=navItems(); if(!items.length) return null;
  const i=idxAt(au.currentTime);
  let at=items.findIndex(x=>x.i===i);
  if(at<0){                       // 不在任何行上：按时间找最近位置
    const t=au.currentTime;
    at = dir>0 ? items.findIndex(x=>x.t> t) : items.length-1;
    if(at<0) at = dir>0 ? items.length-1 : 0;
  }
  const to = at + (dir>0?1:-1);
  if(to<0 || to>=items.length) return items[dir>0?at:0].i;
  return items[to].i;
}
function rowForTime(t){
  let n=-1;
  for(let i=0;i<EROWS.length;i++){ const tt=EROWS[i].t; if(tt!==null && tt<=t) n=i; }
  return n<0?0:n;
}
function highlight(i){
  const ls=viewLines(); const l=ls[i];
  CUR=i;
  if(LRCEDIT){
    document.querySelectorAll('.lerow').forEach(el=>
      el.classList.toggle('cur', +el.dataset.i===i));
    if(!SEL.size) document.querySelector(`.lerow[data-i="${i}"]`)?.scrollIntoView({block:'center',behavior:'smooth'});
  }else{
    document.querySelectorAll('.ln').forEach((el,k)=>el.classList.toggle('on', k===i && !isMetaLine(ls[k])));
    document.querySelectorAll('.ln')[i]?.scrollIntoView({block:'center',behavior:'smooth'});
  }
  // 右侧罗马音：编辑模式下按行号对齐（编辑后的文本与右侧同源），普通模式按时间
  if(LRCEDIT){
    const k=Math.min(i, LINES.length-1);
    if(k>=0){ CUR=k; paint2(k); }
  }else{
    syncSideToTime(lineT(l)===null? au.currentTime : lineT(l));
  }
}
function seek(n){ seekIdx(n, true); }
function paint(n){
  if(n===CUR) return;
  highlight(n);
}
au.onloadedmetadata=()=>{
  if(!LINES.length) return;
  const last=LINES[LINES.length-1].t;
  if(au.duration && last>0 && last/au.duration<0.7){
    document.getElementById('ttl').textContent += `　⚠ 歌词只覆盖到 ${Math.round(last/au.duration*100)}%`;
  }
};
let LRC_CUR=-1;
let LOOP_ROW=-1;

au.ontimeupdate=()=>{
  if(!S || String(PLAYING) !== String(S.idx)) return;
  const t=au.currentTime;
  const i=idxAt(t);
  if(i>=0 && i!==CUR){ highlight(i); }
  if(loop && LOOP_ROW>=0){              // 单句循环：锚定开启时的那一行
    const items=navItems();
    const at=items.findIndex(x=>x.i===LOOP_ROW);
    if(at>=0){
      const start=items[at].t;
      const end=(at+1<items.length)? items[at+1].t : start+8;
      if(t>=end){ au.currentTime=start; highlight(LOOP_ROW); }
    }
  }
};
const playBtn=document.getElementById('play');
function syncPlayBtn(){ playBtn.textContent = au.paused ? '播放' : '暂停'; }
document.getElementById('start').onclick=()=>{ if(!S) return; commitAudio(); au.play().catch(()=>{}); };
playBtn.onclick=()=>{
  if(S && PLAYING!==S.idx){ commitAudio(); au.play().catch(()=>{}); return; }
  if(au.paused){ au.play().catch(()=>{}); } else { au.pause(); }
};
['play','pause','emptied','loadstart','ended','waiting'].forEach(ev=>au.addEventListener(ev, syncPlayBtn));
au.addEventListener('play', syncPlayBtn); au.addEventListener('pause', syncPlayBtn);
document.getElementById('rate').oninput=e=>{au.playbackRate=+e.target.value;document.getElementById('rv').textContent=(+e.target.value).toFixed(2)+'×';};
document.getElementById('prev').onclick=()=>{ const n=nextIdx(-1); if(n!==null) seekIdx(n,true); };
document.getElementById('next').onclick=()=>{ const n=nextIdx(1);  if(n!==null) seekIdx(n,true); };
document.getElementById('t-rm').onclick=e=>{MODE='rm';e.target.classList.add('on');document.getElementById('t-ky').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('t-ky').onclick=e=>{MODE='ky';e.target.classList.add('on');document.getElementById('t-rm').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('rem').onclick=async()=>{
  if(!S || BUSY) return;
  if(LRCEDIT){                                   // 重新匹配前退出 LRC 编辑，并恢复普通歌词面板
    LRCEDIT=false; syncModes();
    if(S) load(S.idx);
  }
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  busy('匹配中…'); lock(this, true);
  let d;
  try{
    const r = await fetch('/api/rematch',{method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'rematch', idx:S.idx, duration:(au.duration||0)})});
    d = await r.json();
  }catch(err){
    done('匹配失败：'+err.message); lock(null,false); return;
  }
  if(!d.candidates || !d.candidates.length){ done('没找到候选，可以试试手动导入 lrc'); lock(null,false); return; }
  done(`找到 ${d.candidates.length} 个候选`); lock(null,false);
  const box=document.createElement('div'); box.className='menu'; box.style.maxWidth='520px';
  box.innerHTML='<div style="font-size:12px;color:#878c95;padding:4px 8px">选一个（分数越高越可能是同一版）</div>';
  d.candidates.forEach(c=>{
    const b=document.createElement('button');
    const mm=Math.floor(c.duration/60), ss=String(Math.round(c.duration%60)).padStart(2,'0');
    const delta=(c.delta===null||c.delta===undefined)?'' : (c.delta>=0?'+':'')+c.delta+'s';
    b.innerHTML=`${c.current?'● ':''}${c.name} · ${c.artist} · ${mm}:${ss} ${delta} · ${c.score}`;
    if(!c.id){                       // 当前这首可能没有 id（来自缓存）→ 不可切换
      b.onclick=ev=>{ev.stopPropagation(); done('当前用的就是这条');};
      b.style.opacity='.6';
    }else b.onclick=async ev=>{ev.stopPropagation();
      box.remove();
      busy('换歌词中…');
      try{
        const r=await fetch('/api/pick',{method:'POST',headers:{'Content-Type':'application/json'},
          body: JSON.stringify({action:'pick', idx:S.idx, id:c.id})});
        const d=await r.json();
        if(!r.ok || !d.ok){ done(d.error||'换歌词失败'); return; }
        await load(d.idx || S.idx);        // 重新拉这一首（已换新歌词）
        loadLib();
        done(`已换成 ${c.name}（${d.lines} 行歌词）`);
      }catch(err){ done('换歌词失败：'+err.message); }
    };
    box.appendChild(b);
  });
  document.body.appendChild(box);
  const r0=document.getElementById('rem').getBoundingClientRect();
  const bw=box.offsetWidth||420, bh=box.offsetHeight||200;
  let left=Math.min(r0.left, window.innerWidth-bw-12);
  left=Math.max(12,left);
  let top=r0.bottom+6;
  if(top+bh>window.innerHeight-12) top=Math.max(12, r0.top-bh-6);   // 放不下就往上开
  box.style.left=left+'px'; box.style.top=top+'px';
};
document.getElementById('loop').onclick=e=>{loop=!loop;e.target.classList.toggle('on',loop);
  if(loop){
    const items=navItems();
    const cur=idxAt(au.currentTime);
    const hit=items.find(x=>x.i>=cur) || items[0];
    LOOP_ROW = hit? hit.i : -1;
  }
  e.target.textContent = loop ? '单句循环：开' : '单句循环';};

document.onkeydown=e=>{
  if(e.target.tagName==='INPUT' || e.isComposing || e.keyCode===229) return;
  if(e.code==='Space'){e.preventDefault();au.paused?au.play():au.pause();}
  if(e.code==='ArrowLeft')document.getElementById('prev').click();
  if(e.code==='ArrowRight')document.getElementById('next').click();
};
