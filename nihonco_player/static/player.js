let S=null, LINES=[], NAV=[], CUR=-1, loop=false, ids=[], MODE='rm', PLAYING=null, EDITMODE=false;
const au=document.getElementById('au'), lyr=document.getElementById('lyr');
let LIB=[], PLS=[], DRAG=null;
let OPEN=new Set();
function saveOpen(){
  fetch('/api/pl',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'ui_open', ids:[...OPEN]})});
}

async function load(i, autoplay){
  const d = await (await fetch('/api/song/'+i)).json();
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
document.getElementById('edit').onclick=e=>{
  EDITMODE=!EDITMODE;
  document.body.classList.toggle('edit', EDITMODE);
  e.target.classList.toggle('on', EDITMODE);
  e.target.textContent = EDITMODE ? '编辑模式：开' : '编辑模式';
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
  col.querySelectorAll('.ln2').forEach(el=>el.onclick=()=>seek(+el.dataset.n));
  if(CUR>=0) paint2(CUR);
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
function seek(n){
  if(!LINES[n]||LINES[n].meta) return;
  const wasPlaying = !au.paused;          // 记住当前是播还是停
  if(PLAYING!==S.idx) commitAudio();      // 换歌（会打断音频）
  au.currentTime = LINES[n].t;
  if(wasPlaying) au.play().catch(()=>{}); // 原来是播的就接着播
  paint(n);
}
function paint(n){
  if(n===CUR)return; CUR=n;
  document.querySelectorAll('.ln').forEach((el,i)=>el.classList.toggle('on',i===n&&!LINES[i].meta));
  const el=document.querySelectorAll('.ln')[n]; if(el)el.scrollIntoView({block:'center',behavior:'smooth'});
  paint2(n);
}
au.onloadedmetadata=()=>{
  if(!LINES.length) return;
  const last=LINES[LINES.length-1].t;
  if(au.duration && last>0 && last/au.duration<0.7){
    document.getElementById('ttl').textContent += `　⚠ 歌词只覆盖到 ${Math.round(last/au.duration*100)}%`;
  }
};
au.ontimeupdate=()=>{
  // 正在看别的歌时，不要让它的歌词跟着当前音频滚动
  if(!S || String(PLAYING) !== String(S.idx)) return;
  const t=au.currentTime; const prev=CUR; let n=-1;
  for(let i=0;i<LINES.length;i++){ if(LINES[i].t<=t) n=i; else break; }
  paint(n);
  // 循环用"上一句"做基准：t 跨过下一句起点时退回上一句开头（尾音不截）
  if(loop&&prev>=0&&!LINES[prev].meta){
    const k=NAV.indexOf(prev); const nx=NAV[k+1];
    if(nx!==undefined&&t>=LINES[nx].t){ au.currentTime=LINES[prev].t; }
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
document.getElementById('prev').onclick=()=>{const k=navIdx(CUR); seek(NAV[Math.max(0,k-1)]);};
document.getElementById('next').onclick=()=>{const k=navIdx(CUR); seek(NAV[Math.min(NAV.length-1,k+1)]);};
document.getElementById('t-rm').onclick=e=>{MODE='rm';e.target.classList.add('on');document.getElementById('t-ky').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('t-ky').onclick=e=>{MODE='ky';e.target.classList.add('on');document.getElementById('t-rm').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('rem').onclick=async()=>{
  if(!S || BUSY) return;
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
    b.onclick=async ev=>{ev.stopPropagation();
      await fetch('/api/pick',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({action:'pick', idx:S.idx, id:c.id})});
      document.getElementById('list').innerHTML=''; loadLib(); load(S.idx); box.remove();};
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
  e.target.textContent = loop ? '单句循环：开' : '单句循环';};

document.onkeydown=e=>{
  if(e.target.tagName==='INPUT' || e.isComposing || e.keyCode===229) return;
  if(e.code==='Space'){e.preventDefault();au.paused?au.play():au.pause();}
  if(e.code==='ArrowLeft')document.getElementById('prev').click();
  if(e.code==='ArrowRight')document.getElementById('next').click();
};
