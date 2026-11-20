/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
// 播放器 · LRC 编辑表格
NH.LRCEDIT = false;

// ── LRC 编辑表格 ────────────────────────────────
NH.EROWS = []; NH.ESEL = -1; NH.SEL = new Set(); NH.MARK = null; NH.EDIRTY = false; NH.UNDO = []; NH.REDO = [];
NH.LRC_METADATA = []; NH.LRC_LOCKED = false; NH.LRC_REPLACING = false;

function setLrcLocked(locked){
  if(locked===NH.LRC_LOCKED) return;
  // 先让有焦点的时间输入框触发 change，再锁定表格。
  if(locked){
    const active=document.activeElement;
    if(active?.closest('#lyr')) active.blur();
    clearTimeout(NH.SAVE_T);
  }
  NH.LRC_LOCKED=locked;
  document.getElementById('lyr').inert=locked;
  document.getElementById('lrcrow2').inert=locked;
}

function snapshot(){
  NH.UNDO.push(JSON.stringify(NH.EROWS)); if(NH.UNDO.length>(NH.UI.undo_steps||50)) NH.UNDO.shift();
  NH.REDO=[]; markDirty();
}

NH.SAVE_T = null; NH.SAVE_PENDING = null; NH.EDIT_REVISION = 0;
function markDirty(){
  NH.EDIT_REVISION++;
  NH.EDIRTY=true;
  const h=document.getElementById('savehint');
  if(h){ h.textContent='未保存…'; h.className='savehint dirty'; }
  clearTimeout(NH.SAVE_T);
  NH.SAVE_T=setTimeout(()=>saveLrc(true), NH.UI.autosave_ms||1500);   // 停止编辑后自动保存
}
function lrcPayload(){
  return NH.EROWS.map(x=>({t:x.t, text:x.text}));
}
async function saveLrc(silent, force){
  if(!NH.S || !NH.LRCEDIT || NH.LRC_REPLACING) return false;
  const song=NH.S;
  // 等前一次写入结束，再读取当前表格，避免旧内容后写覆盖新内容。
  while(NH.SAVE_PENDING){
    await NH.SAVE_PENDING;
    if(NH.S!==song || !NH.LRCEDIT || NH.LRC_REPLACING) return false;
  }
  if(!NH.EDIRTY && !force) return true;
  clearTimeout(NH.SAVE_T);
  const revision=NH.EDIT_REVISION;
  const h=document.getElementById('savehint');
  NH.SAVE_PENDING=(async()=>{
    try{
      const r=await NH.api('/api/lrc',{action:'save', idx:song.idx, lines:lrcPayload()});
      if(!r.ok) throw new Error(r.error||'保存失败');
      if(NH.EDIT_REVISION===revision){
        NH.EDIRTY=false;
        if(h){ h.textContent=`已保存 ${new Date().toLocaleTimeString().slice(0,8)}`; h.className='savehint ok'; }
      }
      return true;
    }catch(e){
      if(h){ h.textContent='保存失败'; h.className='savehint dirty'; }
      if(!silent) NH.done('保存失败：'+e.message);
      return false;
    }
  })();
  try{ return await NH.SAVE_PENDING; }
  finally{ NH.SAVE_PENDING=null; }
}

async function flushLrc(){
  if(!NH.EDIRTY && !NH.SAVE_PENDING) return true;
  if(await saveLrc(true) && !NH.EDIRTY) return true;
  NH.done('歌词保存失败，当前编辑已保留，请重试');
  return false;
}
function undo(){
  if(!NH.UNDO.length) return;
  NH.REDO.push(JSON.stringify(NH.EROWS));
  NH.EROWS=JSON.parse(NH.UNDO.pop()); NH.ESEL=Math.min(NH.ESEL, NH.EROWS.length-1);
  NH.SEL.clear(); markDirty(); renderLrcTable();
}
function redo(){
  if(!NH.REDO.length) return;
  NH.UNDO.push(JSON.stringify(NH.EROWS));
  NH.EROWS=JSON.parse(NH.REDO.pop()); NH.SEL.clear(); markDirty(); renderLrcTable();
}

function lrcFmt(t){ if(t===null||t===undefined) return '';
  const m=Math.floor(t/60), s=(t-m*60);
  return `${String(m).padStart(2,'0')}:${s.toFixed(2).padStart(5,'0')}`; }
function lrcParse(v){
  const m=/^(\d+):(\d+(?:\.\d+)?)$/.exec((v||'').trim()); if(!m) return null;
  return Math.round((+m[1]*60 + +m[2])*100)/100;
}
function lrcText(){
  const rows=NH.EROWS.map(r=>{
    const stamp=lrcFmt(r.t);
    return `${stamp ? `[${stamp}]` : ''}${r.text||''}`;
  });
  for(const tag of NH.LRC_METADATA.slice().reverse()){
    rows.splice(Math.min(tag.before, NH.EROWS.length), 0, tag.text);
  }
  return rows.join('\n')+'\n';
}

NH.LRC_OPEN_REQUEST = 0;
async function openLrcEditor(entering=false){
  if(NH.MATCHING){ NH.done('歌词匹配中，稍后再编辑'); return; }
  const song=NH.S, request=NH.LOAD_REQUEST, opening=++NH.LRC_OPEN_REQUEST;
  const d=await NH.api('/api/lrc',{action:'load', idx:song.idx});
  if(NH.S!==song || request!==NH.LOAD_REQUEST || opening!==NH.LRC_OPEN_REQUEST || (!entering && !NH.LRCEDIT)) return;
  if(!d.ok) throw new Error(d.error||'无法读取歌词');
  if(entering){
    NH.clearToast();
    NH.LRCEDIT=true;
    NH.EDITMODE=false;
    syncModes();
  }
  // 编辑器保留文件顺序及未打点的行，播放视图只展示有时间戳的行。
  NH.LRC_METADATA=d.metadata||[];
  NH.EROWS=(d.lines||[]).map(x=>({t:x.t, text:x.text}));
  if(!NH.EROWS.length) NH.EROWS=[{t:null,text:''}];
  NH.ESEL=0; NH.SEL.clear(); NH.EDIRTY=false; NH.MARK=null;
  NH.UNDO=[]; NH.REDO=[];
  document.getElementById('savehint').textContent='';
  renderLrcTable();
  if(entering){ NH.measureCanvas(); NH.syncWaveLabels(); NH.syncFollow(); if(!NH.WAVE) NH.loadWave(); }
}

function rowHtml(r,i){
  return `<div class="lerow${i===NH.ESEL?' sel':''}${NH.SEL.has(i)?' picked':''}" data-i="${i}">
    <span class="no">${String(i+1).padStart(2,'0')}</span>
    <input class="ts${r.t===null?' none':''}" data-i="${i}" value="${r.t===null?'':lrcFmt(r.t)}" placeholder="mm:ss.xx">
    <span class="bind" data-i="${i}" title="把标记时间写进这一行">↤</span>
    <input class="tx" data-i="${i}" value="${(r.text||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">
    <span class="del" data-i="${i}" title="删除这一行">✕</span>
  </div>`;
}

function renderLrcTable(){
  const box=document.getElementById('lyr');
  box.innerHTML='<div class="letable">'+NH.EROWS.map(rowHtml).join('')+'</div>';
  const rows=box.querySelectorAll('.lerow');

  rows.forEach(el=>{
    el.onclick=e=>{
      if(e.target.tagName==='INPUT') return;      // 输入框内点击：不抢焦点
      if(e.detail>1) return;
      const i=+el.dataset.i;
      const mod = e.metaKey || e.ctrlKey || e.shiftKey;
      if(mod) e.preventDefault();
      if(e.metaKey||e.ctrlKey){ NH.SEL.has(i)?NH.SEL.delete(i):NH.SEL.add(i); }
      else if(e.shiftKey && NH.ESEL>=0){ NH.SEL.clear();
        for(let k=Math.min(NH.ESEL,i);k<=Math.max(NH.ESEL,i);k++) NH.SEL.add(k); }
      else { NH.SEL.clear(); }
      const r=NH.EROWS[i];
      if(!NH.isSelfPlaying() && r && r.t!==null) NH.WMARK[NH.S.idx]=NH.lineT(r);
      NH.ESEL=i; paintSelection();
      if(!mod && NH.isSelfPlaying() && r && r.t!==null) NH.seekIdx(i, true);
    };
    el.ondblclick=ev=>{
      if(ev.target.tagName==='INPUT') return;
      ev.preventDefault();
      NH.playLine(+el.dataset.i);
    };
  });
  box.querySelectorAll('input.ts').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onchange=()=>{
      if(NH.LRC_LOCKED) return;
      const i=+el.dataset.i, v=el.value.trim();
      if(!v){ snapshot(); NH.EROWS[i].t=null; renderLrcTable(); return; }
      const t=lrcParse(v);
      if(t===null){ NH.done('时间戳格式应为 mm:ss.xx'); el.value=lrcFmt(NH.EROWS[i].t); return; }
      snapshot(); NH.EROWS[i].t=t; renderLrcTable();
    };
    el.onkeydown=ev=>{ if(ev.isComposing||ev.keyCode===229) return;
      if(ev.key==='Enter'){ ev.preventDefault(); el.blur(); } };
  });
  box.querySelectorAll('input.tx').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onfocus=()=>{ NH.ESEL=+el.dataset.i; paintSelection(); };
    el.oninput=()=>{
      if(NH.LRC_LOCKED) return;
      NH.EROWS[+el.dataset.i].text=el.value; markDirty();
    };
    el.onkeydown=ev=>{
      if(NH.LRC_LOCKED || ev.isComposing||ev.keyCode===229) return;
      // 光标在行首按 Delete/⌫：把这一行接到上一行末尾
      if((ev.key==='Backspace'||ev.key==='Delete') &&
         el.selectionStart===0 && el.selectionEnd===0){
        const i=+el.dataset.i;
        if(i<=0) return;                       // 第一行没有上一行
        ev.preventDefault();
        const prev=NH.EROWS[i-1], cur=NH.EROWS[i];
        const joinAt=(prev.text||'').length;
        snapshot();
        prev.text=(prev.text||'')+(cur.text||'');
        NH.EROWS.splice(i,1);
        NH.ESEL=i-1; NH.SEL.clear();
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
        NH.EROWS[i].text=left;
        NH.EROWS.splice(i+1, 0, {t:null, text:right});
        NH.ESEL=i+1; NH.SEL.clear(); NH.EDIRTY=true;
        renderLrcTable();
        const nx=document.querySelector(`.lerow[data-i="${i+1}"] input.tx`);
        if(nx){ nx.focus(); nx.setSelectionRange(0,0); }
        document.querySelector(`.lerow[data-i="${i+1}"]`)?.scrollIntoView({block:'center'});
      }
    };
    el.onpaste=ev=>{
      if(NH.LRC_LOCKED) return;
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
      NH.EROWS.splice(at,0,...fresh);
      NH.ESEL=at+fresh.length-1; NH.SEL.clear(); renderLrcTable();
      NH.done(`粘贴了 ${fresh.length} 行`);
    };
  });
  box.querySelectorAll('.bind').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); if(!NH.LRC_LOCKED) bindMark(+el.dataset.i); };
  });
  box.querySelectorAll('.del').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); if(NH.LRC_LOCKED) return;
      snapshot(); NH.EROWS.splice(+el.dataset.i,1);
      if(!NH.EROWS.length) NH.EROWS=[{t:null,text:''}];
      NH.ESEL=Math.min(NH.ESEL,NH.EROWS.length-1); NH.SEL.clear(); renderLrcTable(); };
  });
}

NH.MARQ = null;
document.getElementById('lyr').addEventListener('mousedown', e=>{
  if(!NH.LRCEDIT || !e.shiftKey) return;
  if(e.target.tagName==='INPUT') return;
  e.preventDefault();
  NH.MARQ={x0:e.clientX, y0:e.clientY};
  const d=document.createElement('div'); d.className='marquee'; d.id='marquee';
  document.body.appendChild(d);
});
document.addEventListener('mousemove', e=>{
  if(!NH.MARQ) return;
  const el=document.getElementById('marquee'); if(!el) return;
  const x=Math.min(NH.MARQ.x0,e.clientX), y=Math.min(NH.MARQ.y0,e.clientY);
  const w=Math.abs(e.clientX-NH.MARQ.x0), h=Math.abs(e.clientY-NH.MARQ.y0);
  Object.assign(el.style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'});
});
document.addEventListener('mouseup', e=>{
  if(!NH.MARQ) return;
  const el=document.getElementById('marquee'); if(el) el.remove();
  const x1=Math.min(NH.MARQ.x0,e.clientX), x2=Math.max(NH.MARQ.x0,e.clientX);
  const y1=Math.min(NH.MARQ.y0,e.clientY), y2=Math.max(NH.MARQ.y0,e.clientY);
  NH.MARQ=null;
  const rows=[...document.querySelectorAll('.lerow')];
  const picked=rows.filter(r=>{
    const b=r.getBoundingClientRect();
    return b.bottom>=y1 && b.top<=y2 && b.right>=x1 && b.left<=x2;
  }).map(r=>+r.dataset.i);
  if(!picked.length) return;
  NH.SEL=new Set(picked); NH.ESEL=Math.max(...picked);
  paintSelection();
});
function paintSelection(){
  document.querySelectorAll('.lerow').forEach(el=>{
    const i=+el.dataset.i;
    el.classList.toggle('sel', i===NH.ESEL);
    el.classList.toggle('picked', NH.SEL.has(i));
  });
  if(NH.WAVE && typeof NH.drawWave==='function') NH.drawWave();
}
function insertPos(){
  if(NH.SEL.size) return Math.max(...NH.SEL)+1;
  if(NH.ESEL>=0 && NH.ESEL<NH.EROWS.length) return NH.ESEL+1;
  return NH.EROWS.length;
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
  NH.EROWS.splice(at,0,...fresh);
  NH.ESEL=at+fresh.length-1; NH.SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${NH.ESEL}"]`)?.scrollIntoView({block:'center'});
  return fresh.length;
}
function addRow(at){
  snapshot();
  const pos = (at===undefined) ? insertPos() : at;
  NH.EROWS.splice(pos,0,{t:null,text:''});
  NH.ESEL=pos; NH.SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${pos}"]`)?.scrollIntoView({block:'center'});
}
function delRows(){
  const idx = NH.SEL.size ? [...NH.SEL] : (NH.ESEL>=0?[NH.ESEL]:[]);
  if(!idx.length) return;
  snapshot();
  idx.sort((a,b)=>b-a).forEach(i=>NH.EROWS.splice(i,1));
  if(!NH.EROWS.length) NH.EROWS=[{t:null,text:''}];
  NH.ESEL=Math.min(idx[idx.length-1],NH.EROWS.length-1); NH.SEL.clear(); renderLrcTable();
}
function selectAll(){
  NH.SEL.clear(); for(let i=0;i<NH.EROWS.length;i++) NH.SEL.add(i);
  renderLrcTable();
}
function bindMark(i){
  if(NH.MARK===null){ NH.done('先在波形上点一个位置'); return; }
  snapshot(); NH.EROWS[i].t=NH.MARK;
  NH.ESEL=Math.min(NH.EROWS.length-1, i+1); NH.SEL.clear();
  renderLrcTable();
  document.querySelector(`.lerow[data-i="${NH.ESEL}"]`)?.scrollIntoView({block:'center'});
}

document.addEventListener('paste', e=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED) return;
  if(e.target && e.target.tagName==='INPUT') return;   // 输入框里走原生粘贴
  const text=(e.clipboardData||window.clipboardData||{}).getData
    ? (e.clipboardData||window.clipboardData).getData('text') : '';
  if(!text) return;
  e.preventDefault();
  const n=insertLines(text);
  if(n) NH.done(`粘贴了 ${n} 行`);
});
document.getElementById('lrcadd').onclick=()=>{ if(NH.LRCEDIT && !NH.LRC_LOCKED) addRow(); };
document.getElementById('lrcdel').onclick=()=>{ if(NH.LRCEDIT && !NH.LRC_LOCKED) delRows(); };
document.getElementById('lrcselall').onclick=()=>{ if(NH.LRCEDIT) selectAll(); };
document.getElementById('lrcsaveas').onclick=async()=>{
  if(!NH.LRCEDIT) return;
  const name=(NH.S&&NH.S.title?NH.S.title:'lyrics')+'.nhlrc';
  if(window.pywebview && window.pywebview.api && window.pywebview.api.save_text){
    let ex={ok:false};
    try{ ex=await NH.api('/api/lrc',{action:'export', idx:NH.S.idx, lines:lrcPayload()}); }catch(e){}
    if(!ex.ok){ NH.done('导出失败：'+(ex.error||'未知错误')); return; }
    const p=await window.pywebview.api.save_text(name, ex.nhlrc, ex.lrc);
    NH.done(p ? '已导出 '+p.split('/').pop() : '已取消');
  }else NH.done('当前环境不支持导出');
};
async function replaceLrc(req, pending, success){
  NH.LRC_REPLACING=true;
  setLrcLocked(true);
  NH.busy(pending);
  try{
    // 覆盖操作须等已发出的自动保存结束，避免旧内容覆盖导入或备份。
    await NH.SAVE_PENDING;
    const res=await NH.api('/api/lrc',req);
    if(!res.ok) throw new Error(res.error||'操作失败');
    await openLrcEditor();
    NH.done(success(res));
  }catch(err){
    NH.done('歌词替换失败：'+err.message);
  }finally{
    NH.LRC_REPLACING=false;
    setLrcLocked(false);
  }
}
document.getElementById('lrcimport').onclick=async()=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  const picker=window.pywebview?.api;
  if(!picker?.pick_lrc_text){ NH.done('当前环境不支持选文件'); return; }
  try{
    const r=await picker.pick_lrc_text();
    if(!r?.text || NH.S!==song || !NH.LRCEDIT || NH.LRC_LOCKED) return;
    if(!await NH.uiConfirm('覆盖当前歌词？', `用「${r.name}」覆盖当前歌词，当前内容会被替换`, true)) return;
    await replaceLrc({action:'import_lrc', idx:song.idx, text:r.text}, '导入中…',
      res=>`已导入 ${res.lines} 行${res.backed_up?'（已备份原文件）':''}`);
  }catch(err){ NH.done('导入失败：'+err.message); }
};
document.getElementById('lrcfiledel').onclick=async()=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  if(!await NH.uiConfirm('删除这首歌的歌词文件？',
      'nhlrc 和备份都会被删除，当前编辑内容也会丢弃。\n以后可以重新匹配。', true)) return;
  clearTimeout(NH.SAVE_T);
  NH.EDIRTY=false;
  try{
    if(NH.SAVE_PENDING) await NH.SAVE_PENDING;
    const r=await NH.api('/api/lrc',{action:'delete', idx:song.idx});
    if(!r.ok) throw new Error(r.error||'删除失败');
    NH.NO_MATCH.add(String(song.idx));
    await NH.load(song.idx,false,false);       // 退出 LRC，回到普通页
    NH.done('已删除歌词文件');
  }catch(err){ NH.done('删除失败：'+err.message); }
};
document.getElementById('lrcreset').onclick=async()=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  try{
    const st=await NH.api('/api/lrc',{action:'backup', idx:song.idx});
    if(NH.S!==song || !NH.LRCEDIT || NH.LRC_LOCKED) return;
    if(!st.exists){ NH.done('没有备份（首次保存时才会生成）'); return; }
    const when=new Date(st.mtime*1000).toLocaleString();
    if(!await NH.uiConfirm('恢复到这个备份？', `${when} · ${st.lines} 行\n当前编辑内容会丢失`, true)) return;
    await replaceLrc({action:'restore', idx:song.idx}, '恢复中…',
      res=>`已恢复最初版本（${res.lines} 行）`);
  }catch(err){ NH.done('恢复失败：'+err.message); }
};
document.getElementById('lrcsave').onclick=()=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED) return;
  if(!NH.EROWS.length){ NH.done('没有歌词行'); return; }
  saveLrc(false, true);          // 主动保存：总是写一次
};

document.addEventListener('keydown', e=>{
  if(!NH.LRCEDIT || NH.LRC_LOCKED) return;
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
  body.classList.toggle('fak', NH.EDITMODE);
  body.classList.toggle('lrcedit', NH.LRCEDIT);

  e.textContent='振假名编辑模式：'+(NH.EDITMODE?'开':'关');
  l.textContent='LRC 编辑模式：'+(NH.LRCEDIT?'开':'关');
  l.disabled = !!NH.MATCHING || !NH.S;
  l.title = NH.MATCHING ? '歌词匹配中，稍后再编辑' : '编辑歌词时间轴';
  e.classList.toggle('on', NH.EDITMODE);
  l.classList.toggle('on', NH.LRCEDIT);

  e.title='编辑读音';
  l.title='编辑歌词时间轴';

  const chip=document.getElementById('offchip');
  if(Math.abs(NH.OFFSET)>0.001){
    chip.hidden=false; chip.textContent='偏移 '+(NH.OFFSET>0?'+':'')+NH.OFFSET.toFixed(2)+'s';
  }else chip.hidden=true;
}

document.getElementById('lrcedit').onclick=async e=>{
  if(!NH.S) return;
  if(NH.MATCHING){ NH.done('歌词匹配中，稍后再编辑'); return; }
  if(NH.LRCEDIT) return NH.load(NH.S.idx, false, false);
  const button=e.currentTarget;
  button.disabled=true;
  try{ await openLrcEditor(true); }
  catch(err){ NH.done('打开歌词编辑失败：'+err.message); }
  finally{ button.disabled=false; }
};

document.getElementById('offchip').onclick=async()=>{
  NH.OFFSET=0; if(NH.S) NH.S.offset=0;
  document.getElementById('offval').textContent='0.00s';
  syncModes();
  { const i=NH.idxAt(NH.au.currentTime); if(i>=0) NH.highlight(i); }
  await NH.api('/api/pl',{action:'ui_offset', idx:NH.S?.idx, offset:0});
};

document.getElementById('edit').onclick=()=>{
  if(NH.LRCEDIT) return NH.load(NH.S.idx, false, true);
  NH.LRC_OPEN_REQUEST++;   // 如果正在读取 LRC，保留用户最后选择的模式
  NH.EDITMODE=!NH.EDITMODE;
  syncModes();
};
document.addEventListener('click', async e=>{
  const ew = e.target.closest('.ew');
  if(NH.EDITMODE && ew){
    e.stopPropagation();
    openPicker(ew, [], async v => {
      const lineEl=ew.closest('.ln'); const li=+lineEl.dataset.n; const start=+ew.dataset.start;
      const r=await fetch('/api/line',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({idx:NH.S.idx,line:li,start,reading:v})});
      if(!r.ok) return;
      applyEdit(await r.json());
      flashAt(li, ew.dataset.base);
    });
    return;
  }
  document.querySelectorAll('.menu').forEach(m=>{ if(m.id!=='uiprompt' && m.id!=='uiconfirm') m.remove(); });
  const bc = e.target.closest('.bc');
  if(!bc) return;
  e.stopPropagation();
  const cands = (bc.dataset.cands||'').split('|').filter(Boolean);
  if(NH.EDITMODE){ openPicker(bc, [], (v)=>{ doEdit(bc, v); }); return; }
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
    body: JSON.stringify({idx:NH.S.idx, line:li, start, reading})});
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
          NH.LINES[d.line].rm = d.rm; NH.LINES[d.line].ky = d.ky; NH.LINES[d.line].ruby = d.ruby;
          if(d.rmH) NH.LINES[d.line].rmH = d.rmH;
          if(d.kyH) NH.LINES[d.line].kyH = d.kyH; }
  renderSide();
}



function renderSide(){
  const col=document.getElementById('rmcol');
  col.innerHTML=NH.LINES.map((l,n)=>`<div class="ln2" data-n="${n}">
    <span class="tx">${String(n+1).padStart(2,'0')}</span>${(NH.MODE==='rm'?(l.rmH||l.rm):(l.kyH||l.ky))||''}</div>`).join('');
  col.querySelectorAll('.ln2').forEach(el=>{
    const n=+el.dataset.n;
    el.onclick=e=>{ if(e.detail>1) return; NH.selectLine(n); };
    el.ondblclick=()=>NH.playLine(n);
  });
  if(NH.CUR>=0) paint2(NH.CUR);
}
function syncSideToTime(t){
  if(!NH.LINES.length) return;
  // 取时间最接近的一行（避免边界处偏到下一句）
  let n=-1, best=1e9;
  for(let i=0;i<NH.LINES.length;i++){
    if(NH.isMetaLine(NH.LINES[i])) continue;
    const d=Math.abs(NH.LINES[i].t-t);
    if(d<best){ best=d; n=i; }
  }
  if(n<0) return;
  NH.CUR=n;
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on', i===n && !NH.LINES[i].meta));
  const el=document.querySelectorAll('.ln2')[n];
  if(el) el.scrollIntoView({block:'center'});
}
function paint2(n){
  // 与左侧同一判定：按文本判断 meta，而不是看 payload 里的 meta 字段
  const meta = !NH.LINES[n] || NH.isMetaLine(NH.LINES[n]);
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on', i===n && !meta));
  if(meta) return;
  const el2=document.querySelectorAll('.ln2')[n];
  if(el2)el2.scrollIntoView({block:'center'});
}

Object.assign(NH, {setLrcLocked, snapshot, markDirty, lrcPayload, saveLrc, flushLrc, undo, redo, lrcFmt, lrcParse, lrcText, openLrcEditor, rowHtml, renderLrcTable, paintSelection, insertPos, insertLines, addRow, delRows, selectAll, bindMark, replaceLrc, syncModes, openPicker, doEdit, flashAt, applyEdit, renderSide, syncSideToTime, paint2});
})();
