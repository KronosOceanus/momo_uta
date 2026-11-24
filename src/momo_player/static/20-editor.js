/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
// 播放器 · LRC 编辑表格
NH.VIEW_MODE = 'normal';

// ── LRC 编辑表格 ────────────────────────────────
NH.EROWS = []; NH.ESEL = -1; NH.SEL = new Set(); NH.MARK = null; NH.EDIRTY = false; NH.UNDO = []; NH.REDO = [];
NH.TEXT_EDIT_ROW = null;
NH.TRANS_EDIT = false;
NH.LRC_METADATA = []; NH.LRC_LOCKED = false; NH.LRC_REPLACING = false; NH.LRC_FLUSHING = false; NH.LRC_CONFLICT = false; NH.ROWS_MODE = false;

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
  if(!NH.LRC_CONFLICT)
    NH.SAVE_T=setTimeout(()=>saveLrc(true), NH.UI.autosave_ms||1500); // 冲突时暂停自动保存
  NH.paintTicks?.();
}
function newLid(){
  const bytes = new Uint8Array(4);
  if(window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
  else for(let i=0;i<bytes.length;i++) bytes[i]=Math.floor(Math.random()*256);
  return 'l_'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}
function ensureLid(row){
  if(!row.lid) row.lid=newLid();
  return row.lid;
}
function newRowId(){
  const bytes=new Uint8Array(4);
  if(window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
  else for(let i=0;i<bytes.length;i++) bytes[i]=Math.floor(Math.random()*256);
  return 'r_'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}
function rowKind(text){
  const t=(text||'').trim();
  if(!t) return 'blank';
  if(/^\[(ar|al|ti|au|by|offset|length|re|ve|la|id|tool):/i.test(t)) return 'metadata';
  return 'lyric';
}
function beginTextEdit(i){
  if(NH.TEXT_EDIT_ROW!==i){
    snapshot();
    NH.TEXT_EDIT_ROW=i;
  }
}
function retokenizeRow(row, nextText){
  const old=row.text||'';
  if(old===nextText) return;
  const wasEmpty=!old.trim(), nowEmpty=!nextText.trim();
  if(nowEmpty){
    // lyric → blank：内容身份和译文一起清掉。
    row.text=nextText; row.kind='blank';
    row.lid=null; row.tokens=[]; row.trans='';
    return;
  }
  if(wasEmpty){
    // blank → lyric：新内容，新身份，不继承旧译文。
    row.text=nextText; row.kind=rowKind(nextText);
    row.lid=newLid(); row.tokens=[]; row.trans='';
    return;
  }
  ensureLid(row);
  const tokens=Array.isArray(row.tokens)?row.tokens:[];
  let p=0;
  while(p<old.length && p<nextText.length && old[p]===nextText[p]) p++;
  let s=0;
  while(s<old.length-p && s<nextText.length-p &&
        old[old.length-1-s]===nextText[nextText.length-1-s]) s++;
  const changedEnd=old.length-s;
  const shift=nextText.length-old.length;
  row.text=nextText;
  row.kind=rowKind(nextText);
  row.tokens=tokens.flatMap(t=>{
    if(t.end<=p) return [t];
    if(t.start>=changedEnd) return [{...t, start:t.start+shift, end:t.end+shift}];
    return [];
  });
}
function sliceTokens(row, start, end, shift=0){
  return (row.tokens||[]).filter(t=>t.start>=start && t.end<=end)
    .map(t=>({...t, start:t.start+shift, end:t.end+shift}));
}
function splitRow(row, pos){
  const text=row.text||'';
  const left=text.slice(0,pos), right=text.slice(pos);
  const leftTokens=sliceTokens(row,0,pos);
  const rightTokens=sliceTokens(row,pos,text.length,-pos);
  ensureLid(row);
  const oldLid=row.lid, oldT=row.t, oldTrans=row.trans||'';
  const leftEmpty=!left.trim(), rightEmpty=!right.trim();
  // 内容侧保留 lid/t/trans；空侧新身份、无译文。
  let rightLid=newLid(), rightT=null, rightTrans='';
  if(leftEmpty && !rightEmpty){
    row.lid=newLid(); row.t=null; row.trans='';
    rightLid=oldLid; rightT=oldT; rightTrans=oldTrans;
  }
  row.text=left; row.tokens=leftTokens; row.kind=rowKind(left);
  return {id:newRowId(), kind:rowKind(right), t:rightT, text:right,
          trans:rightTrans, lid:rightLid, tokens:rightTokens};
}
function mergeRows(prev, cur){
  const prevText=prev.text||'', curText=cur.text||'';
  const useCurLid=!prevText.trim() && curText.trim() && cur.lid;
  const lid=useCurLid ? cur.lid : ensureLid(prev);
  const offset=prevText.length;
  prev.text=prevText+curText;
  prev.kind=rowKind(prev.text);
  prev.lid=lid;
  prev.tokens=[...(prev.tokens||[]), ...(cur.tokens||[]).map(t=>({
    ...t, start:t.start+offset, end:t.end+offset
  }))];
}
function mergeSavedIds(ids){
  if(!Array.isArray(ids)) return;
  for(const item of ids){
    const i=+item.i, row=NH.EROWS[i];
    if(!row || (row.text||'')!==(item.text||'')) continue;
    if(item.lid) row.lid=item.lid;
    if(Array.isArray(item.tokens)) row.tokens=item.tokens;
  }
}
function lrcPayload(){
  if(NH.ROWS_MODE){
    return NH.EROWS.map(x=>{
      const row={id:x.id||newRowId(), kind:x.kind||rowKind(x.text), t:x.t, text:x.text||'',
                 trans:x.trans||''};
      if(x.lid) row.lid=x.lid;
      if(Array.isArray(x.tokens) && x.tokens.length) row.tokens=x.tokens.map(t=>({...t}));
      return row;
    });
  }
  return NH.EROWS.map(x=>{
    const row={t:x.t, text:x.text, trans:x.trans||''};
    if(x.lid) row.lid=x.lid;
    if(Array.isArray(x.tokens) && x.tokens.length){
      row.tokens=x.tokens.map(t=>({tid:t.tid, start:t.start, end:t.end, base:t.base}));
    }
    return row;
  });
}
function syncTransBtn(){
  const b=document.getElementById('lrctrans'); if(!b) return;
  b.textContent='翻译：'+(NH.TRANS_EDIT?'开':'关');
  b.classList.toggle('on', NH.TRANS_EDIT);
}
async function saveLrc(silent, force){
  if(!NH.S || NH.VIEW_MODE!=='lrc' || (NH.LRC_REPLACING && !NH.LRC_FLUSHING)) return false;
  const song=NH.S;
  // 等前一次写入结束，再读取当前表格，避免旧内容后写覆盖新内容。
  while(NH.SAVE_PENDING){
    await NH.SAVE_PENDING;
    if(NH.S!==song || NH.VIEW_MODE!=='lrc' || NH.LRC_REPLACING) return false;
  }
  if(NH.LRC_CONFLICT && !force) return false;
  if(!NH.EDIRTY && !force) return true;
  clearTimeout(NH.SAVE_T);
  const revision=NH.EDIT_REVISION;
  const h=document.getElementById('savehint');
  NH.SAVE_PENDING=(async()=>{
    try{
      const body={action:NH.ROWS_MODE?'save_rows':'save', uid:song.uid, version:NH.LRC_VERSION};
      if(NH.ROWS_MODE) body.rows=lrcPayload(); else body.lines=lrcPayload();
      const r=await NH.api('/api/lrc',body);
      if(r && r.conflict){
        NH.LRC_CONFLICT=true;
        if(h){ h.textContent='服务端歌词已更新'; h.className='savehint dirty'; }
        return false;
      }
      if(!r.ok) throw new Error(r.error||'保存失败');
      NH.LRC_CONFLICT=false;
      if(r.version) NH.LRC_VERSION=r.version;
      if(NH.EDIT_REVISION===revision){
        mergeSavedIds(r.ids);
        NH.EDIRTY=false;
        if(h){ h.textContent=r.refresh_ok===false
          ? '已保存，但曲库刷新失败；重启后仍以磁盘为准'
          : `已保存 ${new Date().toLocaleTimeString().slice(0,8)}`;
          h.className=r.refresh_ok===false?'savehint dirty':'savehint ok'; }
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

async function reloadLrcFromServer(refresh){
  clearTimeout(NH.SAVE_T);
  NH.EDIRTY=false;
  NH.LRC_CONFLICT=false;
  if(refresh && NH.VIEW_MODE==='lrc'){
    try{ return await openLrcEditor(true,{discardDraft:true}); }
    catch(e){ NH.done('重新加载歌词失败：'+e.message); return false; }
  }
  return true;
}

async function overwriteLrc(){
  const song=NH.S;
  if(!song) return false;
  const d=await NH.api('/api/lrc',{action:'load', uid:song.uid});
  if(!d.ok){ NH.done('读取最新歌词失败：'+(d.error||'未知错误')); return false; }
  if(NH.S!==song) return false;
  NH.LRC_VERSION=d.version||null;
  NH.LRC_CONFLICT=false;
  NH.EDIRTY=true;
  const ok=await saveLrc(true,true);
  if(ok && !NH.EDIRTY) return true;
  NH.done('用本地覆盖失败，草稿仍保留');
  return false;
}

let CONFLICT_DIALOG=null;
async function resolveLrcConflict(refresh=true){
  if(CONFLICT_DIALOG) return await CONFLICT_DIALOG;
  CONFLICT_DIALOG=(async()=>{
    const action=await NH.uiLrcConflict();
    if(action==='reload') return await reloadLrcFromServer(refresh);
    if(action===true) return await overwriteLrc();
    return false;
  })();
  try{ return await CONFLICT_DIALOG; }
  finally{ CONFLICT_DIALOG=null; }
}

async function flushLrc(){
  if(NH.LRC_CONFLICT) return await resolveLrcConflict(false);
  if(!NH.EDIRTY && !NH.SAVE_PENDING) return true;
  if(await saveLrc(true) && !NH.EDIRTY) return true;
  if(NH.LRC_CONFLICT) return await resolveLrcConflict(false);
  NH.done('歌词保存失败，当前编辑已保留，请重试');
  return false;
}
function undo(){
  if(!NH.UNDO.length) return;
  NH.REDO.push(JSON.stringify(NH.EROWS));
  NH.TEXT_EDIT_ROW=null;
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
  if(NH.ROWS_MODE){
    return NH.EROWS.map(r=>{
      if((r.kind||rowKind(r.text))==='metadata') return r.text||'';
      const stamp=lrcFmt(r.t);
      return `${stamp ? `[${stamp}]` : ''}${r.text||''}`;
    }).join('\n')+'\n';
  }
  const rows=NH.EROWS.map(r=>{
    const stamp=lrcFmt(r.t);
    return `${stamp ? `[${stamp}]` : ''}${r.text||''}`;
  });
  for(const tag of NH.LRC_METADATA.slice().reverse()){
    rows.splice(Math.min(tag.before, NH.EROWS.length), 0, tag.text);
  }
  return rows.join('\n')+'\n';
}

function editorRowIndex(line, rows){
  if(!line || !Array.isArray(rows) || !rows.length) return 0;
  if(line.lid){
    const byLid=rows.findIndex(r=>r && r.lid===line.lid);
    if(byLid>=0) return byLid;
  }
  if(line.t!==null && line.t!==undefined){
    let best=-1, dist=Infinity;
    rows.forEach((r,i)=>{
      if(!r || r.t===null || r.t===undefined) return;
      const d=Math.abs(+r.t - +line.t);
      if(d<dist){ dist=d; best=i; }
    });
    if(best>=0) return best;
  }
  return 0;
}

async function openLrcEditor(entering=false, opts={}){
  if(NH.viewMatching()){ NH.done('歌词匹配中，稍后再编辑'); return; }
  // 重新读取服务端文档前，先把当前草稿保存；失败则不能清掉 dirty。
  if(!opts.discardDraft && (NH.EDIRTY || NH.SAVE_PENDING)){
    if(!await flushLrc()) return false;
  }
  const revision=NH.EDIT_REVISION;
  const song=NH.S, request=NH.currentToken('load'), opening=NH.track('lrcOpen');
  const d=await NH.api('/api/lrc',{action:'load', uid:song.uid});
  if(NH.S!==song || !NH.isCurrent('load',request) || !NH.isCurrent('lrcOpen',opening) || (!entering && NH.VIEW_MODE!=='lrc')) return false;
  if(!d.ok) throw new Error(d.error||'无法读取歌词');
  if(NH.EDIT_REVISION!==revision){
    NH.done('加载期间有编辑，已保留当前草稿');
    return false;
  }
  if(entering){
    NH.clearToast();
    NH.VIEW_MODE='lrc';
    syncModes();
  }
  // 编辑器保留文件顺序及未打点的行，播放视图只展示有时间戳的行。
  NH.LRC_VERSION=d.version||null;
  NH.ROWS_MODE=Array.isArray(d.rows);
  if(NH.ROWS_MODE){
    NH.LRC_METADATA=[];
    NH.EROWS=d.rows.map(x=>{
      const row={id:x.id||newRowId(), kind:x.kind||rowKind(x.text), t:x.t,
                 text:x.text||'', trans:x.trans||''};
      if(x.lid) row.lid=x.lid;
      if(Array.isArray(x.tokens) && x.tokens.length) row.tokens=x.tokens;
      return row;
    });
  }else{
    NH.LRC_METADATA=d.metadata||[];
    const lids=d.line_ids||{};
    NH.EROWS=(d.lines||[]).map((x,i)=>{
      const row={t:x.t, text:x.text, trans:x.trans||''};
      const lid=x.lid||lids[i];
      if(lid) row.lid=lid;
      const tokens=x.tokens||[];
      if(tokens.length) row.tokens=tokens;
      return row;
    });
  }
  NH.TRANS_EDIT=false; syncTransBtn();
  if(!NH.EROWS.length) NH.EROWS=[{id:newRowId(),kind:'blank',t:null,text:'',trans:''}];
  const targetLine = entering && NH.CUR >= 0 ? NH.LINES[NH.CUR] : null;
  NH.ESEL=entering ? editorRowIndex(targetLine, NH.EROWS) : 0;
  NH.SEL.clear(); NH.EDIRTY=false; NH.LRC_CONFLICT=false; NH.MARK=null;
  NH.TEXT_EDIT_ROW=null;
  NH.UNDO=[]; NH.REDO=[];
  document.getElementById('savehint').textContent='';
  renderLrcTable();
  if(entering){
    const row=document.querySelector(`.lerow[data-i="${NH.ESEL}"]`);
    row?.scrollIntoView({block:'center'});
  }
  NH.paintTicks?.();
  if(entering){ NH.measureCanvas(); NH.syncWaveLabels(); NH.syncFollow(); if(!NH.WAVE) NH.loadWave(); }
  return true;
}

function rowHtml(r,i){
  return `<div class="lerow${i===NH.ESEL?' sel':''}${NH.SEL.has(i)?' picked':''}" data-i="${i}">
    <span class="no">${String(i+1).padStart(2,'0')}</span>
    <input class="ts${r.t===null?' none':''}" data-i="${i}" value="${r.t===null?'':lrcFmt(r.t)}" placeholder="mm:ss.xx">
    <span class="bind" data-i="${i}" title="把标记时间写进这一行">↤</span>
    <input class="tx" data-i="${i}" value="${(r.text||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">
    ${NH.TRANS_EDIT?`<input class="tx trans" data-i="${i}" value="${(r.trans||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">`:''}
    <span class="del" data-i="${i}" title="删除这一行">✕</span>
  </div>`;
}

function renderLrcTable(){
  const box=document.getElementById('lyr');
  box.innerHTML=`<div class="letable${NH.TRANS_EDIT?' transon':''}">`+NH.EROWS.map(rowHtml).join('')+'</div>';
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
      if(!NH.isSelfPlaying() && r && r.t!==null) NH.WMARK[NH.S.uid]=NH.lineT(r);
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
  box.querySelectorAll('input.tx:not(.trans)').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onfocus=()=>{ NH.ESEL=+el.dataset.i; paintSelection(); };
    el.onblur=()=>{ NH.TEXT_EDIT_ROW=null; };
    el.oninput=()=>{
      if(NH.LRC_LOCKED) return;
      const i=+el.dataset.i;
      beginTextEdit(i);
      retokenizeRow(NH.EROWS[i], el.value);
      markDirty();
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
        mergeRows(prev, cur);
        prev.trans=[prev.trans||'', cur.trans||''].filter(x=>x).join(' ');
        NH.EROWS.splice(i,1);
        NH.TEXT_EDIT_ROW=null;
        NH.ESEL=i-1; NH.SEL.clear();
        renderLrcTable();
        const pv=document.querySelector(`.lerow[data-i="${i-1}"] input.tx`);
        if(pv){ pv.focus(); pv.setSelectionRange(joinAt, joinAt); }
        document.querySelector(`.lerow[data-i="${i-1}"]`)?.scrollIntoView({block:'center'});
        return;
      }
      if(ev.key==='Enter'){
        ev.preventDefault();
        const i=+el.dataset.i, pos=el.selectionStart;
        snapshot();
        const right=splitRow(NH.EROWS[i], pos);
        NH.EROWS.splice(i+1, 0, right);
        NH.TEXT_EDIT_ROW=null;
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
        return m ? {id:newRowId(), kind:rowKind(m[3]), t:Math.round((+m[1]*60 + +m[2])*100)/100,
                    text:m[3], trans:'', lid:newLid()}
                 : {id:newRowId(), kind:rowKind(x), t:null, text:x, trans:'', lid:newLid()};
      });
      NH.EROWS.splice(at,0,...fresh);
      NH.ESEL=at+fresh.length-1; NH.SEL.clear(); renderLrcTable();
      NH.done(`粘贴了 ${fresh.length} 行`);
    };
  });
  box.querySelectorAll('input.tx.trans').forEach(el=>{
    el.onclick=e=>e.stopPropagation();
    el.onfocus=()=>{ NH.ESEL=+el.dataset.i; paintSelection(); };
    el.oninput=()=>{
      if(NH.LRC_LOCKED) return;
      NH.EROWS[+el.dataset.i].trans=el.value;
      markDirty();
    };
    el.onkeydown=ev=>{
      if(NH.LRC_LOCKED || ev.isComposing||ev.keyCode===229) return;
      if(ev.key==='Enter'){ ev.preventDefault(); el.blur(); }
    };
  });

  box.querySelectorAll('.bind').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); if(!NH.LRC_LOCKED) bindMark(+el.dataset.i); };
  });
  box.querySelectorAll('.del').forEach(el=>{
    el.onclick=e=>{ e.stopPropagation(); if(NH.LRC_LOCKED) return;
      snapshot(); NH.EROWS.splice(+el.dataset.i,1);
      if(!NH.EROWS.length) NH.EROWS=[{id:newRowId(),kind:'blank',t:null,text:'',trans:''}];
      NH.ESEL=Math.min(NH.ESEL,NH.EROWS.length-1); NH.SEL.clear(); renderLrcTable(); };
  });
}

NH.MARQ = null;
document.getElementById('lyr').addEventListener('mousedown', e=>{
  if(NH.VIEW_MODE!=='lrc' || !e.shiftKey) return;
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
    return m ? {id:newRowId(), kind:rowKind(m[3]), t:Math.round((+m[1]*60 + +m[2])*100)/100,
                text:m[3], trans:'', lid:newLid()}
             : {id:newRowId(), kind:rowKind(x), t:null, text:x, trans:'', lid:newLid()};
  });
  NH.EROWS.splice(at,0,...fresh);
  NH.ESEL=at+fresh.length-1; NH.SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${NH.ESEL}"]`)?.scrollIntoView({block:'center'});
  return fresh.length;
}
function addRow(at){
  snapshot();
  const pos = (at===undefined) ? insertPos() : at;
  NH.EROWS.splice(pos,0,{id:newRowId(),kind:'blank',t:null,text:'',trans:'',lid:newLid()});
  NH.ESEL=pos; NH.SEL.clear(); renderLrcTable();
  document.querySelector(`.lerow[data-i="${pos}"]`)?.scrollIntoView({block:'center'});
}
function delRows(){
  const idx = NH.SEL.size ? [...NH.SEL] : (NH.ESEL>=0?[NH.ESEL]:[]);
  if(!idx.length) return;
  snapshot();
  idx.sort((a,b)=>b-a).forEach(i=>NH.EROWS.splice(i,1));
  if(!NH.EROWS.length) NH.EROWS=[{id:newRowId(),kind:'blank',t:null,text:'',trans:''}];
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
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED) return;
  if(e.target && e.target.tagName==='INPUT') return;   // 输入框里走原生粘贴
  const text=(e.clipboardData||window.clipboardData||{}).getData
    ? (e.clipboardData||window.clipboardData).getData('text') : '';
  if(!text) return;
  e.preventDefault();
  const n=insertLines(text);
  if(n) NH.done(`粘贴了 ${n} 行`);
});
document.getElementById('lrcadd').onclick=()=>{ if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED) addRow(); };
document.getElementById('lrcdel').onclick=()=>{ if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED) delRows(); };
document.getElementById('lrcselall').onclick=()=>{ if(NH.VIEW_MODE==='lrc') selectAll(); };
document.getElementById('lrctrans').onclick=()=>{ NH.TRANS_EDIT=!NH.TRANS_EDIT; syncTransBtn(); renderLrcTable(); };
document.getElementById('lrcsaveas').onclick=async()=>{
  if(NH.VIEW_MODE!=='lrc') return;
  const name=(NH.S&&NH.S.title?NH.S.title:'lyrics')+'.nhlrc';
  if(window.pywebview && window.pywebview.api && window.pywebview.api.save_text){
    let ex={ok:false};
    const body={action:'export', uid:NH.S.uid};
    if(NH.ROWS_MODE) body.rows=lrcPayload(); else body.lines=lrcPayload();
    try{ ex=await NH.api('/api/lrc',body); }catch(e){}
    if(!ex.ok){ NH.done('导出失败：'+(ex.error||'未知错误')); return; }
    const p=await window.pywebview.api.save_text(name, ex.nhlrc, ex.lrc);
    NH.done(p ? '已导出 '+p.split('/').pop() : '已取消');
  }else NH.done('当前环境不支持导出');
};
async function saveBeforeReplace(){
  const pending=NH.SAVE_PENDING;
  if(pending){
    if(!await pending) return false;
    if(!NH.EDIRTY) return true;
  }
  if(NH.EDIRTY) return await flushLrc();
  return true;
}

async function replaceLrc(req, pending, success){
  const song=NH.S;
  if(!song) return;
  NH.LRC_REPLACING=true;
  NH.LRC_FLUSHING=true;          // 允许本次覆盖前的 flush，同时阻止切歌
  setLrcLocked(true);
  NH.busy(pending);
  try{
    // 覆盖前先把当前草稿落盘；保存失败时不能继续丢弃草稿。
    if(!await saveBeforeReplace()) return;
    if(NH.S!==song || NH.VIEW_MODE!=='lrc') return;
    const res=await NH.api('/api/lrc',{...req, version:NH.LRC_VERSION});
    if(!res.ok) throw new Error(res.error||'操作失败');
    if(NH.S!==song || NH.VIEW_MODE!=='lrc') return;
    await openLrcEditor();
    if(NH.S!==song) return;
    NH.done(success(res));
  }catch(err){
    NH.done('歌词替换失败：'+err.message);
  }finally{
    NH.LRC_FLUSHING=false;
    NH.LRC_REPLACING=false;
    setLrcLocked(false);
  }
}
document.getElementById('lrcimport').onclick=async()=>{
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  const picker=window.pywebview?.api;
  if(!picker?.pick_lrc_text){ NH.done('当前环境不支持选文件'); return; }
  try{
    const r=await picker.pick_lrc_text();
    if(!r?.text || NH.S!==song || NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED) return;
    if(!await NH.uiConfirm('覆盖当前歌词？', `用「${r.name}」覆盖当前歌词，当前内容会被替换`, true)) return;
    await replaceLrc({action:'import_lrc', uid:song.uid, text:r.text}, '导入中…',
      res=>`已导入 ${res.lines} 行${res.backed_up?'（已备份原文件）':''}`);
  }catch(err){ NH.done('导入失败：'+err.message); }
};
document.getElementById('lrcfiledel').onclick=async()=>{
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  if(!await NH.uiConfirm('删除这首歌的歌词文件？',
      '歌词将被禁用，备份会保留。\n这首歌仍可播放，但不会自动匹配歌词。\n以后可以通过重新匹配或保存新歌词重新启用。', true)) return;
  NH.LRC_REPLACING=true;
  NH.LRC_FLUSHING=true;                           // 允许删除前的 flush，同时阻止切歌
  setLrcLocked(true);                             // 和导入/恢复共用切歌锁
  try{
    if(!await saveBeforeReplace()) return;
    if(NH.S!==song || NH.VIEW_MODE!=='lrc') return;
    const r=await NH.api('/api/lrc',{action:'delete', uid:song.uid, version:NH.LRC_VERSION});
    if(!r.ok) throw new Error(r.error||'删除失败');
    if(NH.S!==song || NH.VIEW_MODE!=='lrc') return;  // 迟到响应不碰新会话
    NH.EDIRTY=false;
    NH.LRC_FLUSHING=false;
    NH.LRC_REPLACING=false;
    setLrcLocked(false);
    await NH.load(song.uid,false,'normal');     // 退出 LRC，回到普通页
    NH.done('已禁用这首歌的歌词');
  }catch(err){
    if(NH.S===song && NH.EDIRTY) markDirty();    // 删除失败：草稿仍算未保存
    NH.done('删除失败：'+err.message);
  }finally{
    NH.LRC_FLUSHING=false;
    NH.LRC_REPLACING=false;
    setLrcLocked(false);
  }
};
document.getElementById('lrcreset').onclick=async()=>{
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED || !NH.S) return;
  const song=NH.S;
  try{
    const st=await NH.api('/api/lrc',{action:'backup', uid:song.uid});
    if(NH.S!==song || NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED) return;
    if(!st.exists){ NH.done('没有备份（首次保存时才会生成）'); return; }
    const when=new Date(st.mtime*1000).toLocaleString();
    if(!await NH.uiConfirm('恢复到这个备份？', `${when} · ${st.lines} 行\n当前编辑内容会丢失`, true)) return;
    await replaceLrc({action:'restore', uid:song.uid}, '恢复中…',
      res=>`已恢复最初版本（${res.lines} 行）`);
  }catch(err){ NH.done('恢复失败：'+err.message); }
};
document.getElementById('lrcsave').onclick=async()=>{
  if(NH.VIEW_MODE!=='lrc' || NH.LRC_LOCKED) return;
  if(!NH.EROWS.length){ NH.done('没有歌词行'); return; }
  const ok=await saveLrc(false, true);   // 主动保存：总是写一次
  if(!ok && NH.LRC_CONFLICT) await resolveLrcConflict(true);
};

function syncModes(){
  const e=document.getElementById('edit'), l=document.getElementById('lrcedit');
  const rem=document.getElementById('rem');
  const start=document.getElementById('start');
  const enabled=!!NH.S && !NH.viewMatching();
  if(start) start.disabled=!NH.S;
  const body=document.body;
  body.classList.toggle('fak', NH.VIEW_MODE==='kana');
  body.classList.toggle('lrcedit', NH.VIEW_MODE==='lrc');

  e.textContent='振假名编辑模式：'+(NH.VIEW_MODE==='kana'?'开':'关');
  l.textContent='LRC 编辑模式：'+(NH.VIEW_MODE==='lrc'?'开':'关');
  l.disabled = !enabled;
  e.disabled = !enabled;
  if(rem){
    rem.disabled = !enabled;
    rem.title = NH.viewMatching() ? '歌词匹配中' : '重新匹配当前歌曲的歌词';
  }
  l.title = NH.viewMatching() ? '歌词匹配中，稍后再编辑' : '编辑歌词时间轴';
  e.classList.toggle('on', NH.VIEW_MODE==='kana');
  l.classList.toggle('on', NH.VIEW_MODE==='lrc');

  e.title='编辑读音';

  const chip=document.getElementById('offchip');
  if(Math.abs(NH.OFFSET)>0.001){
    chip.hidden=false; chip.textContent='偏移 '+(NH.OFFSET>0?'+':'')+NH.OFFSET.toFixed(2)+'s';
  }else chip.hidden=true;
}

document.getElementById('lrcedit').onclick=async e=>{
  if(!NH.S) return;
  if(NH.viewMatching()){ NH.done('歌词匹配中，稍后再编辑'); return; }
  if(NH.VIEW_MODE==='lrc') return NH.load(NH.S.uid, false, 'normal');
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
  const r=await NH.api('/api/pl',{action:'ui_offset', uid:NH.S?.uid, offset:0});
  if(r && r.ok===false) NH.done(r.error||'歌曲已不可用');
};

document.getElementById('edit').onclick=()=>{
  if(NH.VIEW_MODE==='lrc') return NH.load(NH.S.uid, false, 'kana');
  NH.track('lrcOpen');   // 如果正在读取 LRC，保留用户最后选择的模式
  NH.VIEW_MODE = NH.VIEW_MODE==='kana' ? 'normal' : 'kana';
  syncModes();
};
document.addEventListener('click', async e=>{
  const ew = e.target.closest('.ew');
  if(NH.VIEW_MODE==='kana' && ew){
    e.stopPropagation();
    openPicker(ew, [], async v => {
      const lineEl=ew.closest('.ln'); const li=+lineEl.dataset.n; const start=+ew.dataset.start;
      try{
        const d=await NH.api('/api/line',{uid:NH.S.uid,line:li,lid:lineEl.dataset.lid, version:NH.S?.version,
                                         start,reading:v});
        if(d.ok===false) throw new Error(d.error||'歌词行已变化');
        applyEdit(d);
        flashAt(li, ew.dataset.base);
      }catch(err){ NH.done('改读音失败：'+err.message); }
    });
    return;
  }
  document.querySelectorAll('.menu').forEach(m=>{ if(m.id!=='uiprompt' && m.id!=='uiconfirm') m.remove(); });
  const bc = e.target.closest('.bc');
  if(!bc) return;
  e.stopPropagation();
  const cands = (bc.dataset.cands||'').split('|').filter(Boolean);
  if(NH.VIEW_MODE==='kana'){ openPicker(bc, [], (v)=>{ doEdit(bc, v); }); return; }
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
    const submit=()=>{ const v=inp.value.trim();
      if(!/^[ぁ-んー]+$/.test(v)){ inp.style.borderColor='var(--danger)'; return; }
      m.remove(); onPick(v); };
    inp.onkeydown=ev=>{
      if(ev.isComposing || ev.keyCode===229) return;   // 输入法组词中，别抢 Enter
      if(ev.key==='Enter') submit();
      if(ev.key==='Escape') m.remove();
    };
    m.appendChild(inp);
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
  try{
    const lid = lineEl.dataset.lid;
    const d = await NH.api('/api/line',{uid:NH.S.uid, line:li, lid, start, reading, version:NH.S?.version});
    if(d.ok===false) throw new Error(d.error||'歌词行已变化');
    applyEdit(d);
    flashAt(li, bc.dataset.base);
  }catch(err){ NH.done('改读音失败：'+err.message); }
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
  if(!NH.S) return;
  if(d.uid && String(d.uid)!==String(NH.S.uid)) return;
  let li = d.line;
  if(d.lid){
    const found = NH.LINES.findIndex(x=>x.lid===d.lid);
    if(found<0){ NH.done('歌词行已变化，请重新加载'); return; }
    li = found;
  }
  if(d.version){ NH.LRC_VERSION=d.version; NH.S.version=d.version; }
  const el = document.querySelectorAll('.ln')[li];
  if(!el) return;
  const trans = NH.LINES[li].trans
    ? `<div class="lntrans">${String(NH.LINES[li].trans).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`
    : '';
  el.innerHTML = `<span class="tx">${String(li+1).padStart(2,'0')}</span> ` + d.ruby + trans;
  NH.LINES[li].rm = d.rm; NH.LINES[li].ky = d.ky; NH.LINES[li].ruby = d.ruby;
  if(d.rmH) NH.LINES[li].rmH = d.rmH;
  if(d.kyH) NH.LINES[li].kyH = d.kyH;
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
function paint2(n){
  // 与左侧同一判定：按文本判断 meta，而不是看 payload 里的 meta 字段
  const meta = !NH.LINES[n] || NH.isMetaLine(NH.LINES[n]);
  document.querySelectorAll('.ln2').forEach((el,i)=>el.classList.toggle('on', i===n && !meta));
  if(meta) return;
  const el2=document.querySelectorAll('.ln2')[n];
  if(el2)el2.scrollIntoView({block:'center'});
}

Object.assign(NH, {editorRowIndex, saveBeforeReplace, resolveLrcConflict, reloadLrcFromServer, overwriteLrc, setLrcLocked, snapshot, markDirty, beginTextEdit, retokenizeRow, newLid, ensureLid, sliceTokens, splitRow, mergeRows, mergeSavedIds, lrcPayload, saveLrc, flushLrc, undo, redo, lrcFmt, lrcParse, lrcText, openLrcEditor, rowHtml, renderLrcTable, paintSelection, insertPos, insertLines, addRow, delRows, selectAll, bindMark, replaceLrc, syncModes, openPicker, doEdit, flashAt, applyEdit, renderSide, paint2});
syncModes();   // 启动时没有 S：三个入口和“开始”都置灰
})();
