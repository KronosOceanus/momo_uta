// 播放器 · LRC 编辑表格
let LRCEDIT=false;

// ── LRC 编辑表格 ────────────────────────────────
let EROWS=[], ESEL=-1, SEL=new Set(), MARK=null, EDIRTY=false, UNDO=[], REDO=[];
let LRC_METADATA=[], LRC_LOCKED=false, LRC_REPLACING=false;

function setLrcLocked(locked){
  if(locked===LRC_LOCKED) return;
  // 先让有焦点的时间输入框触发 change，再锁定表格。
  if(locked){
    const active=document.activeElement;
    if(active?.closest('#lyr')) active.blur();
    clearTimeout(SAVE_T);
  }
  LRC_LOCKED=locked;
  document.getElementById('lyr').inert=locked;
  document.getElementById('lrcrow2').inert=locked;
}

function snapshot(){
  UNDO.push(JSON.stringify(EROWS)); if(UNDO.length>50) UNDO.shift();
  REDO=[]; markDirty();
}

let SAVE_T=null, SAVE_PENDING=null, EDIT_REVISION=0;
function markDirty(){
  EDIT_REVISION++;
  EDIRTY=true;
  const h=document.getElementById('savehint');
  if(h){ h.textContent='未保存…'; h.className='savehint dirty'; }
  clearTimeout(SAVE_T);
  SAVE_T=setTimeout(()=>saveLrc(true), 1500);     // 停止编辑 1.5 秒后自动保存
}
function lrcPayload(){
  return EROWS.map(x=>({t:x.t, text:x.text}));
}
async function saveLrc(silent, force){
  if(!S || !LRCEDIT || LRC_REPLACING) return false;
  const song=S;
  // 等前一次写入结束，再读取当前表格，避免旧内容后写覆盖新内容。
  while(SAVE_PENDING){
    await SAVE_PENDING;
    if(S!==song || !LRCEDIT || LRC_REPLACING) return false;
  }
  if(!EDIRTY && !force) return true;
  clearTimeout(SAVE_T);
  const revision=EDIT_REVISION;
  const h=document.getElementById('savehint');
  SAVE_PENDING=(async()=>{
    try{
      const r=await api('/api/lrc',{action:'save', idx:song.idx, lines:lrcPayload()});
      if(!r.ok) throw new Error(r.error||'保存失败');
      if(EDIT_REVISION===revision){
        EDIRTY=false;
        if(h){ h.textContent=`已保存 ${new Date().toLocaleTimeString().slice(0,8)}`; h.className='savehint ok'; }
        if(!silent) done(`已保存 ${r.lines} 行${r.backed_up?'（已备份原文件）':''}`);
      }
      return true;
    }catch(e){
      if(h){ h.textContent='保存失败'; h.className='savehint dirty'; }
      if(!silent) done('保存失败：'+e.message);
      return false;
    }
  })();
  try{ return await SAVE_PENDING; }
  finally{ SAVE_PENDING=null; }
}

async function flushLrc(){
  if(!EDIRTY && !SAVE_PENDING) return true;
  if(await saveLrc(true) && !EDIRTY) return true;
  done('歌词保存失败，当前编辑已保留，请重试');
  return false;
}
function undo(){
  if(!UNDO.length) return;
  REDO.push(JSON.stringify(EROWS));
  EROWS=JSON.parse(UNDO.pop()); ESEL=Math.min(ESEL, EROWS.length-1);
  SEL.clear(); markDirty(); renderLrcTable();
}
function redo(){
  if(!REDO.length) return;
  UNDO.push(JSON.stringify(EROWS));
  EROWS=JSON.parse(REDO.pop()); SEL.clear(); markDirty(); renderLrcTable();
}

function lrcFmt(t){ if(t===null||t===undefined) return '';
  const m=Math.floor(t/60), s=(t-m*60);
  return `${String(m).padStart(2,'0')}:${s.toFixed(2).padStart(5,'0')}`; }
function lrcParse(v){
  const m=/^(\d+):(\d+(?:\.\d+)?)$/.exec((v||'').trim()); if(!m) return null;
  return Math.round((+m[1]*60 + +m[2])*100)/100;
}
function lrcText(){
  const rows=EROWS.map(r=>{
    const stamp=lrcFmt(r.t);
    return `${stamp ? `[${stamp}]` : ''}${r.text||''}`;
  });
  for(const tag of LRC_METADATA.slice().reverse()){
    rows.splice(Math.min(tag.before, EROWS.length), 0, tag.text);
  }
  return rows.join('\n')+'\n';
}

let LRC_OPEN_REQUEST=0;
async function openLrcEditor(entering=false){
  const song=S, request=LOAD_REQUEST, opening=++LRC_OPEN_REQUEST;
  const d=await api('/api/lrc',{action:'load', idx:song.idx});
  if(S!==song || request!==LOAD_REQUEST || opening!==LRC_OPEN_REQUEST || (!entering && !LRCEDIT)) return;
  if(!d.ok) throw new Error(d.error||'无法读取歌词');
  if(entering){
    LRCEDIT=true;
    EDITMODE=false;
    syncModes();
  }
  // 编辑器保留文件顺序及未打点的行，播放视图只展示有时间戳的行。
  LRC_METADATA=d.metadata||[];
  EROWS=(d.lines||[]).map(x=>({t:x.t, text:x.text}));
  if(!EROWS.length) EROWS=[{t:null,text:''}];
  ESEL=0; SEL.clear(); EDIRTY=false; MARK=null;
  UNDO=[]; REDO=[];
  document.getElementById('savehint').textContent='';
  renderLrcTable();
  if(entering){ measureCanvas(); syncWaveLabels(); syncFollow(); if(!WAVE) loadWave(); }
}

function rowHtml(r,i){
  return `<div class="lerow${i===ESEL?' sel':''}${SEL.has(i)?' picked':''}" data-i="${i}">
    <span class="no">${String(i+1).padStart(2,'0')}</span>
    <input class="ts${r.t===null?' none':''}" data-i="${i}" value="${r.t===null?'':lrcFmt(r.t)}" placeholder="mm:ss.xx">
    <span class="bind" data-i="${i}" title="把标记时间写进这一行">↤</span>
    <input class="tx" data-i="${i}" value="${(r.text||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">
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
      if(LRC_LOCKED) return;
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
    el.oninput=()=>{
      if(LRC_LOCKED) return;
      EROWS[+el.dataset.i].text=el.value; markDirty();
    };
    el.onkeydown=ev=>{
      if(LRC_LOCKED || ev.isComposing||ev.keyCode===229) return;
      // 光标在行首按 Delete/⌫：把这一行接到上一行末尾
      if((ev.key==='Backspace'||ev.key==='Delete') &&
         el.selectionStart===0 && el.selectionEnd===0){
        const i=+el.dataset.i;
        if(i<=0) return;                       // 第一行没有上一行
        ev.preventDefault();
        const prev=EROWS[i-1], cur=EROWS[i];
        const joinAt=(prev.text||'').length;
        snapshot();
        prev.text=(prev.text||'')+(cur.text||'');
        EROWS.splice(i,1);
        ESEL=i-1; SEL.clear();
        renderLrcTable();
        const pv=document.querySelector(`.lerow[data-i="${i-1}"] input.tx`);
        if(pv){ pv.focus(); pv.setSelectionRange(joinAt, joinAt); }
        document.querySelector(`.lerow[data-i="${i-1}"]`)?.scrollIntoView({block:'center'});
        return;
      }
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
      if(LRC_LOCKED) return;
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
    el.onclick=e=>{ e.stopPropagation(); if(!LRC_LOCKED) bindMark(+el.dataset.i); };
  });
  box.querySelectorAll('.del').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); if(LRC_LOCKED) return;
      snapshot(); EROWS.splice(+el.dataset.i,1);
      if(!EROWS.length) EROWS=[{t:null,text:''}];
      ESEL=Math.min(ESEL,EROWS.length-1); SEL.clear(); renderLrcTable(); };
  });
}

let MARQ=null;
document.getElementById('lyr').addEventListener('mousedown', e=>{
  if(!LRCEDIT || !e.shiftKey) return;
  if(e.target.tagName==='INPUT') return;
  e.preventDefault();
  MARQ={x0:e.clientX, y0:e.clientY};
  const d=document.createElement('div'); d.className='marquee'; d.id='marquee';
  document.body.appendChild(d);
});
document.addEventListener('mousemove', e=>{
  if(!MARQ) return;
  const el=document.getElementById('marquee'); if(!el) return;
  const x=Math.min(MARQ.x0,e.clientX), y=Math.min(MARQ.y0,e.clientY);
  const w=Math.abs(e.clientX-MARQ.x0), h=Math.abs(e.clientY-MARQ.y0);
  Object.assign(el.style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'});
});
document.addEventListener('mouseup', e=>{
  if(!MARQ) return;
  const el=document.getElementById('marquee'); if(el) el.remove();
  const x1=Math.min(MARQ.x0,e.clientX), x2=Math.max(MARQ.x0,e.clientX);
  const y1=Math.min(MARQ.y0,e.clientY), y2=Math.max(MARQ.y0,e.clientY);
  MARQ=null;
  const rows=[...document.querySelectorAll('.lerow')];
  const picked=rows.filter(r=>{
    const b=r.getBoundingClientRect();
    return b.bottom>=y1 && b.top<=y2 && b.right>=x1 && b.left<=x2;
  }).map(r=>+r.dataset.i);
  if(!picked.length) return;
  SEL=new Set(picked); ESEL=Math.max(...picked);
  paintSelection();
});
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
  if(!LRCEDIT || LRC_LOCKED) return;
  if(e.target && e.target.tagName==='INPUT') return;   // 输入框里走原生粘贴
  const text=(e.clipboardData||window.clipboardData||{}).getData
    ? (e.clipboardData||window.clipboardData).getData('text') : '';
  if(!text) return;
  e.preventDefault();
  const n=insertLines(text);
  if(n) done(`粘贴了 ${n} 行`);
});
document.getElementById('lrcadd').onclick=()=>{ if(LRCEDIT && !LRC_LOCKED) addRow(); };
document.getElementById('lrcdel').onclick=()=>{ if(LRCEDIT && !LRC_LOCKED) delRows(); };
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
async function replaceLrc(req, pending, success){
  LRC_REPLACING=true;
  setLrcLocked(true);
  busy(pending);
  try{
    // 覆盖操作须等已发出的自动保存结束，避免旧内容覆盖导入或备份。
    await SAVE_PENDING;
    const res=await api('/api/lrc',req);
    if(!res.ok) throw new Error(res.error||'操作失败');
    await openLrcEditor();
    done(success(res));
  }catch(err){
    done('歌词替换失败：'+err.message);
  }finally{
    LRC_REPLACING=false;
    setLrcLocked(false);
  }
}
document.getElementById('lrcimport').onclick=async()=>{
  if(!LRCEDIT || LRC_LOCKED || !S) return;
  const song=S;
  const picker=window.pywebview?.api;
  if(!picker?.pick_lrc_text){ done('当前环境不支持选文件'); return; }
  try{
    const r=await picker.pick_lrc_text();
    if(!r?.text || S!==song || !LRCEDIT || LRC_LOCKED) return;
    if(!confirm(`用「${r.name}」覆盖当前歌词？当前内容会被替换`)) return;
    await replaceLrc({action:'import_lrc', idx:song.idx, text:r.text}, '导入中…',
      res=>`已导入 ${res.lines} 行${res.backed_up?'（已备份原文件）':''}`);
  }catch(err){ done('导入失败：'+err.message); }
};
document.getElementById('lrcreset').onclick=async()=>{
  if(!LRCEDIT || LRC_LOCKED || !S) return;
  const song=S;
  try{
    const st=await api('/api/lrc',{action:'backup', idx:song.idx});
    if(S!==song || !LRCEDIT || LRC_LOCKED) return;
    if(!st.exists){ done('没有备份（首次保存时才会生成）'); return; }
    const when=new Date(st.mtime*1000).toLocaleString();
    if(!confirm(`恢复到这个备份？\n${when} · ${st.lines} 行\n当前编辑内容会丢失`)) return;
    await replaceLrc({action:'restore', idx:song.idx}, '恢复中…',
      res=>`已恢复最初版本（${res.lines} 行）`);
  }catch(err){ done('恢复失败：'+err.message); }
};
document.getElementById('lrcsave').onclick=()=>{
  if(!LRCEDIT || LRC_LOCKED) return;
  if(!EROWS.length){ done('没有歌词行'); return; }
  saveLrc(false, true);          // 主动保存：总是写一次
};

document.addEventListener('keydown', e=>{
  if(!LRCEDIT || LRC_LOCKED) return;
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

document.getElementById('lrcedit').onclick=async e=>{
  if(!S) return;
  if(LRCEDIT) return load(S.idx, false, false);
  const button=e.currentTarget;
  button.disabled=true;
  try{ await openLrcEditor(true); }
  catch(err){ done('打开歌词编辑失败：'+err.message); }
  finally{ button.disabled=false; }
};

document.getElementById('offchip').onclick=async()=>{
  OFFSET=0; if(S) S.offset=0;
  document.getElementById('offval').textContent='0.00s';
  syncModes();
  { const i=idxAt(au.currentTime); if(i>=0) highlight(i); }
  await api('/api/pl',{action:'ui_offset', idx:S?.idx, offset:0});
};

document.getElementById('edit').onclick=()=>{
  if(LRCEDIT) return load(S.idx, false, true);
  LRC_OPEN_REQUEST++;   // 如果正在读取 LRC，保留用户最后选择的模式
  EDITMODE=!EDITMODE;
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
  if(el) el.scrollIntoView({block:'center'});
}
function paint2(n){
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on',i===n&&!LINES[i].meta));
  const el2=document.querySelectorAll('.ln2')[n];
  if(el2)el2.scrollIntoView({block:'center'});
}
