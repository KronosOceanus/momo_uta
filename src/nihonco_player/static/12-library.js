/* 命名空间模块：歌单 / 多选 / 右键 / 拖拽 / 导入 */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
async function loadLib(){
  const d = await NH.api('/api/pl');
  NH.PLS = d.lists || d;
  if(d.open && d.open.length) NH.OPEN = new Set(d.open);
  NH.LIB = NH.PLS.flatMap(g=>g.items);
  NH.renderList();
  if(d.auto_rebuild) scheduleAutoRebuild();
}

function scheduleAutoRebuild(){
  if(NH.AUTO_REBUILD) return;
  NH.AUTO_REBUILD=true;
  const run=async()=>{
    if(NH.VIEW_MODE==='lrc' || NH.BUSY || NH.TOAST_BUSY){ setTimeout(run, NH.UI.busy_retry_ms||5000); return; }
    if(NH.PLAYING_UID!==null && NH.au && !NH.au.paused){ setTimeout(run, NH.UI.busy_retry_ms||5000); return; }
    NH.busy('发现缺失歌曲，正在重建索引…');
    try{
      const job=await NH.api('/api/jobs',{kind:'rebuild'});
      const st=await NH.waitJob(job.id);
      if(st.state==='failed') throw new Error(st.error || '重建失败');
      await NH.loadLib();
      const r=st.result || {};
      NH.done(r.recovered>0 ? `索引已重建，找回 ${r.recovered} 首` : '索引已重建，仍有缺失歌曲');
    }catch(err){
      NH.done('重建索引失败：'+err.message);
    }
  };
  setTimeout(run, NH.UI.auto_rebuild_ms||8000);
}

function applyLists(r){
  if(!r || !r.lists) return;
  NH.PLS = r.lists;
  NH.LIB = NH.PLS.flatMap(g => g.items);
  NH.renderList();
}

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
      + its.map(x=>`<div class="it${NH.SEL_LIST===g.id && NH.SELU.has(x.uid)?' picked':''}" data-i="${x.idx}" data-u="${x.uid}" data-hl="${x.has_lyric===false?0:1}" data-playing="${String(NH.PLAYING_UID)===String(x.uid)?'1':''}" draggable="true">
          <div class="t1"><span class="orig">${x.orig||x.title}</span>
            ${(x.orig||'')===(x.title||'')?'':`<span class="mch">${x.title}</span>`}</div>
          <div class="ar">${x.artist}</div>
          ${x.has_lyric===false?'<span class="noly" title="无歌词">无词</span>':''}
          <b class="del" data-act="del-entry" data-u="${x.uid}" data-id="${g.id}" title="从歌单移除">✕</b>
        </div>`).join('')
      + `</div></div>`;
  });
  document.getElementById('list').innerHTML=html||'<div class="empty">没有歌</div>';
  NH.markPlaying?.();
}

function syncLyricMark(uid, has){
  document.querySelectorAll('.it').forEach(el=>{ if(el.dataset.u!==String(uid)) return;
    el.dataset.hl = has ? '1' : '0';
    const old = el.querySelector('.noly');
    if(has){ if(old) old.remove(); return; }
    if(old) return;
    const b = document.createElement('span');
    b.className = 'noly'; b.title = '无歌词'; b.textContent = '无词';
    const del = el.querySelector('.del');
    if(del) del.before(b); else el.appendChild(b);
  });
}
NH.syncLyricMark = syncLyricMark;

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

// 搜索框：输入即过滤（轻量防抖）
let Q_TIMER = null;
document.getElementById('q').addEventListener('input', () => {
  clearTimeout(Q_TIMER);
  Q_TIMER = setTimeout(renderList, 120);
});

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
    if(danger) b.style.color='var(--danger)';
    b.onclick=ev=>{ ev.stopPropagation(); closeCtx(); fn(); };
    box.appendChild(b);
  };
  mk('导入音乐…', ()=>doImport(g.id, false));
  mk('导入音乐+LRC…', ()=>doImport(g.id, true));
  if(!g.locked) mk('重命名…', async ()=>{
    const name=await NH.uiPrompt('新的歌单名', g.name);
    if(!name || name===g.name) return;
    const r=await NH.api('/api/pl',{action:'list_rename',id:g.id,name});
    NH.applyLists(r);
  });
  mk('清空歌单', async ()=>{
    if(!await NH.uiConfirm(`清空「${g.name}」？`, '歌本身不会丢')) return;
    const r=await NH.api('/api/pl',{action:'list_clear',id:g.id});
    NH.applyLists(r);
  });
  if(!g.locked) mk('删除歌单', async ()=>{
    if(!await NH.uiConfirm(`删除歌单「${g.name}」？`, '歌本身不会丢', true)) return;
    const r=await NH.api('/api/pl',{action:'list_delete',id:g.id});
    NH.applyLists(r);
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
  b.style.color='var(--danger)';
  b.onclick=async ev=>{
    ev.stopPropagation(); closeCtx();
    const ok=await NH.uiConfirm(n===1?'从歌单移除？':`移除选中的 ${n} 首？`, '歌本身不会丢', true);
    if(!ok) return;
    const r=await NH.api('/api/pl',{action:'entries_remove',list:lid,uids});
    NH.SELU.clear(); NH.SEL_LIST=null; NH.SEL_ANCHOR=null;
    NH.applyLists(r);
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
    const r=await NH.api('/api/pl',{action:'entry_remove',list:lid,uid});
    if(NH.SEL_LIST===lid) NH.SELU.delete(uid);
    NH.applyLists(r); paintSongSel();
    return;
  }

  const head=e.target.closest('[data-act="toggle"]');
  if(head){ const id=head.dataset.id;
    NH.OPEN.has(id)?NH.OPEN.delete(id):NH.OPEN.add(id); NH.saveOpen(); return NH.renderList(); }

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
    NH.load(row.dataset.u);
  }
});
document.getElementById('list').addEventListener('dblclick', e=>{
  const row=e.target.closest('.it');
  if(row) NH.load(row.dataset.u, true);
});
document.getElementById('list').addEventListener('dragstart', e=>{
  const row=e.target.closest('.it'), head=e.target.closest('.plh');
  if(row){
    const pl=row.closest('.pl'), lid=pl.dataset.id, uid=row.dataset.u;
    let uids=[uid];
    if(NH.SEL_LIST===lid && NH.SELU.has(uid)){       // 拖已多选的行 → 整组移动
      uids=[...pl.querySelectorAll('.it')].map(x=>x.dataset.u)
        .filter(u=>NH.SELU.has(u));
    }
    NH.DRAG={kind:'songs', uids, from:lid};
    e.dataTransfer.effectAllowed='move';
    e.dataTransfer.setData('text/plain', uids.length>1?`${uids.length} songs`:'song');
  }else if(head){ const pl=head.parentElement;
    if(pl.dataset.id==='default'){ NH.DRAG=null; return; }   // 默认歌单固定置顶
    NH.DRAG={kind:'list', id:pl.dataset.id};
    e.dataTransfer.setData('text/plain','list');
  }
});
document.getElementById('list').addEventListener('dragover', e=>{
  if(e.target.closest('.it')||e.target.closest('.plh')||e.target.closest('.plb')) e.preventDefault();
});
document.getElementById('list').addEventListener('drop', async e=>{
  if(!NH.DRAG) return;
  const targetRow=e.target.closest('.it');
  const targetPl=(e.target.closest('.pl')||{}).dataset;
  const toPl=targetPl && targetPl.id;
  if(NH.DRAG.kind==='songs'){
    const moved=NH.DRAG.uids||[];
    if(!toPl || !moved.length){ NH.DRAG=null; return; }
    const from=NH.DRAG.from;
    const before=targetRow?targetRow.dataset.u:null;
    let changed=false;
    if(from===toPl){
      if(before && !moved.includes(before)){        // 同歌单内多选重排
        const uids=[...e.target.closest('.plb').querySelectorAll('.it')].map(x=>x.dataset.u);
        const arr=uids.filter(u=>!moved.includes(u));
        const at=arr.indexOf(before);
        if(at>=0){
          arr.splice(at,0,...moved);
          await NH.api('/api/pl',{action:'entry_reorder',list:toPl,uids:arr});
          changed=true;
        }
      }
    }else{                                           // 跨歌单：整组移动，可选插到目标歌前面
      await NH.api('/api/pl',{action:'entries_move',from,to:toPl,uids:moved,before});
      changed=true;
    }
    if(changed) clearSongSel();
  }else if(NH.DRAG.kind==='list' && toPl && NH.DRAG.id!==toPl){
    const ids=[...document.querySelectorAll('.pl')].map(x=>x.dataset.id).filter(x=>x!=='default');
    ids.splice(ids.indexOf(NH.DRAG.id),1);
    ids.splice(ids.indexOf(toPl),0,NH.DRAG.id);
    await NH.api('/api/pl',{action:'list_reorder',ids});
  }
  NH.DRAG=null; NH.loadLib();
});

// 导入：选完直接导入，只弹一条消息
async function doImport(listId, withLrc, btn){
  let paths=[];
  const api_ = window.pywebview && window.pywebview.api;
  if(api_ && api_.pick_any){
    paths = await api_.pick_any() || [];        // 一个对话框，文件/文件夹都行
  }else{
    paths = ((await NH.uiPrompt('路径（多个用 ; 分隔）'))||'').split(';').map(x=>x.trim()).filter(Boolean);
  }
  if(!paths.length) return;
  NH.busy('导入中…');
  try{
    const r = await NH.api('/api/pl',{action:'import', list:listId, paths, with_lrc:!!withLrc});
    if(r.lists) NH.PLS=r.lists; NH.LIB=NH.PLS.flatMap(g=>g.items); NH.renderList();
    if(r.ok===false){ NH.done(r.error||'导入失败'); return; }
    const bits=[`新增 ${r.imported} 首`];
    if(r.pending_count) bits.push(`其中 ${r.pending_count} 首待匹配歌词`);
    if(r.overwritten) bits.push(`覆盖 ${r.overwritten} 首歌词`);
    if(r.unpaired) bits.push(`${r.unpaired} 个 lrc 未配对`);
    if(r.already) bits.push(`${r.already} 首已在歌单`);
    NH.done(bits.join('，')); lock(btn, false);
  }catch(err){
    NH.done('导入失败：'+err.message); lock(btn, false);
  }
}

document.getElementById('newlist').onclick=async e=>{
  e.stopPropagation();
  const name=await NH.uiPrompt('新歌单名称'); if(!name) return;
  const r=await NH.api('/api/pl',{action:'list_create',name});
  NH.applyLists(r);
};
const _ERR_SEEN = new Map();

NH.loadLib=loadLib;
NH.applyLists=applyLists;
NH.renderList=renderList;
NH.syncLyricMark=syncLyricMark;
NH.closeCtx=closeCtx;
NH.openPlMenu=openPlMenu;
NH.doImport=doImport;
loadLib().catch(async()=>{
  await new Promise(r=>setTimeout(r,600));
  loadLib().catch(e=>{ NH.toast('加载歌单失败：'+e.message); NH.reportClientError('load_lib', e.message, e.stack); });
});
})();
