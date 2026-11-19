// 播放器 · 统一播放层与播放条
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
// ── 精确定位：旧声音立刻停 → 定位 → 能出声了再继续播 ──
function onceEvent(name, ms){
  return new Promise(res=>{
    let done=false;
    const fin=()=>{ if(done) return; done=true; au.removeEventListener(name, fin); res(); };
    au.addEventListener(name, fin); setTimeout(fin, ms);
  });
}
function audioReady(){
  if(au.readyState>=1 && isFinite(au.duration)) return Promise.resolve();
  return onceEvent('loadedmetadata', 900);
}
let SEEK_SEQ=0, SEEK_WAS_PLAYING=false;
async function seekPrecise(t){
  t=Math.max(0, t);
  if(SEEK_SEQ===0) SEEK_WAS_PLAYING=!au.paused;   // 连点时以第一次的状态为准
  const seq=++SEEK_SEQ;
  if(SEEK_WAS_PLAYING) au.pause();         // 画面与旧声音都在此停下
  await audioReady();
  if(seq!==SEEK_SEQ) return;
  const seeked=onceEvent('seeked', 900);
  au.currentTime=t;
  paintTransport();
  await seeked;
  if(seq!==SEEK_SEQ) return;
  if(au.readyState<3) await onceEvent('canplay', 900);
  if(seq!==SEEK_SEQ) return;
  if(SEEK_WAS_PLAYING) await au.play().catch(()=>{});
  paintTransport();
  SEEK_SEQ=0;                              // 这一轮结束，下一次重新取播放状态
}

function seekIdx(i, keepPlaying){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(PLAYING!==S.idx) commitAudio();
  const t=Math.max(0, lineT(l));
  seekPrecise(t);                              // 是否续播由 seekPrecise 自己判断
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
    // 播放中不自动滚动表格：换行时滚动正是"画面顿一下"的可疑来源
    if(!SEL.size && au.paused)
      document.querySelector(`.lerow[data-i="${i}"]`)?.scrollIntoView({block:'nearest'});
  }else{
    document.querySelectorAll('.ln').forEach((el,k)=>el.classList.toggle('on', k===i && !isMetaLine(ls[k])));
    document.querySelectorAll('.ln')[i]?.scrollIntoView({block:'nearest'});
  }
  // 播放时 rAF 循环已在画波形，这里不再重复画
  // 右侧罗马音：编辑模式下按行号对齐（编辑后的文本与右侧同源），普通模式按时间
  if(LRCEDIT){
    // 右侧罗马音在编辑模式下隐藏，不需要联动
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
  if(i>=0){
    // 只在"索引变了"或"DOM 上确实没亮"时重绘（后者修 UI 被重建后不重画的问题）
    const el=LRCEDIT ? document.querySelector(`.lerow[data-i="${i}"]`)
                     : document.querySelectorAll('.ln')[i];
    const lit=LRCEDIT ? (el && el.classList.contains('cur'))
                      : (el && el.classList.contains('on'));
    if(i!==CUR || !lit) highlight(i);
  }
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

// ── 自绘播放条 ────────────────────────────────
function fmtTime(t){
  if(!isFinite(t)||t<0) t=0;
  const m=Math.floor(t/60), s=Math.floor(t%60);
  return `${m}:${String(s).padStart(2,'0')}`;
}
function paintTransport(){
  const dur=isFinite(au.duration)?au.duration:0;
  const cur=au.currentTime||0;
  document.getElementById('tcur').textContent=fmtTime(cur);
  document.getElementById('tdur').textContent=fmtTime(dur);
  const pct=dur?Math.min(100, cur/dur*100):0;
  document.getElementById('fill').style.width=pct+'%';
  document.getElementById('thumb').style.left=pct+'%';
  document.getElementById('play2').textContent = au.paused ? '▶' : '⏸';
  document.getElementById('mute').textContent = au.muted||au.volume===0 ? '🔇' : '🔊';
}
function paintTicks(){
  const box=document.getElementById('ticks'); box.innerHTML='';
  const dur=isFinite(au.duration)?au.duration:0; if(!dur) return;
  const frag=document.createDocumentFragment();
  (LINES||[]).forEach(l=>{
    if(!l || l.t==null) return;
    const i=document.createElement('i');
    i.style.left=(l.t/dur*100)+'%';
    frag.appendChild(i);
  });
  box.appendChild(frag);
}
function seekToClientX(x){
  const r=document.getElementById('seek').getBoundingClientRect();
  const ratio=Math.max(0,Math.min(1,(x-r.left)/r.width));
  const dur=isFinite(au.duration)?au.duration:0;
  if(dur) au.currentTime=ratio*dur;
  paintTransport();
}
(function bindTransport(){
  const seek=document.getElementById('seek');
  let dragging=false;
  seek.addEventListener('mousedown', e=>{ dragging=true; seekToClientX(e.clientX); });
  document.addEventListener('mousemove', e=>{ if(dragging) seekToClientX(e.clientX); });
  document.addEventListener('mouseup', ()=>{ dragging=false; });
  document.getElementById('play2').onclick=()=>{ if(au.paused) au.play().catch(()=>{}); else au.pause(); };
  document.getElementById('back10').onclick=()=>{ seekPrecise(Math.max(0, au.currentTime-10)); };
  document.getElementById('fwd10').onclick=()=>{ seekPrecise(Math.min(au.duration||0, au.currentTime+10)); };
  document.getElementById('volume').oninput=e=>{ au.volume=+e.target.value; au.muted=au.volume===0; paintTransport(); };
  document.getElementById('mute').onclick=()=>{ au.muted=!au.muted; paintTransport(); };
  ['timeupdate','loadedmetadata','durationchange','play','pause','volumechange'].forEach(ev=>
    au.addEventListener(ev, ()=>{ paintTransport(); if(ev==='loadedmetadata') paintTicks(); }));
})();

const playBtn=document.getElementById('play');
function syncPlayBtn(){ playBtn.textContent = au.paused ? '播放' : '暂停'; }
document.getElementById('start').onclick=()=>{ if(!S) return; commitAudio(); au.play().catch(()=>{}); };
playBtn.onclick=()=>{
  if(S && PLAYING!==S.idx){ commitAudio(); au.play().catch(()=>{}); return; }
  if(au.paused){ au.play().catch(()=>{}); } else { au.pause(); }
};
['play','pause','emptied','loadstart','ended','waiting'].forEach(ev=>au.addEventListener(ev, syncPlayBtn));
['pause','seeked','loadedmetadata'].forEach(ev=>au.addEventListener(ev, ()=>{ if(typeof WAVE!=='undefined' && WAVE && LRCEDIT) drawWave(); }));
au.addEventListener('play', syncPlayBtn); au.addEventListener('pause', syncPlayBtn);
document.getElementById('rate').oninput=e=>{au.playbackRate=+e.target.value;document.getElementById('rv').textContent=(+e.target.value).toFixed(2)+'×';};
document.getElementById('prev').onclick=()=>{ const n=nextIdx(-1); if(n!==null) seekIdx(n,true); };
document.getElementById('next').onclick=()=>{ const n=nextIdx(1);  if(n!==null) seekIdx(n,true); };
document.getElementById('t-rm').onclick=e=>{MODE='rm';e.target.classList.add('on');document.getElementById('t-ky').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('t-ky').onclick=e=>{MODE='ky';e.target.classList.add('on');document.getElementById('t-rm').classList.remove('on');const l=LINES[CUR];renderSide();};
document.getElementById('rem').onclick=async()=>{
  if(!S || BUSY) return;
  if(LRCEDIT && !await load(S.idx, false, false)) return;
  const song=S;
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  busy('匹配中…'); lock(this, true);
  let d;
  try{
    const r = await fetch('/api/rematch',{method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'rematch', idx:song.idx, duration:(au.duration||0)})});
    d = await r.json();
  }catch(err){
    done('匹配失败：'+err.message); lock(null,false); return;
  }
  if(S!==song || LRCEDIT){ lock(null,false); return; }
  if(!d.candidates || !d.candidates.length){ done('没找到候选，可以试试手动导入 lrc'); lock(null,false); return; }
  done(`找到 ${d.candidates.length} 个候选`); lock(null,false);
  const box=document.createElement('div'); box.className='menu'; box.style.maxWidth='520px';
  box.innerHTML='<div style="font-size:12px;color:#878c95;padding:4px 8px">选一个（分数越高越可能是同一版）· 候选来自网络，不读本地缓存</div>';
  d.candidates.forEach(c=>{
    const b=document.createElement('button');
    const mm=Math.floor(c.duration/60), ss=String(Math.round(c.duration%60)).padStart(2,'0');
    const delta=(c.delta===null||c.delta===undefined)?'' : (c.delta>=0?'+':'')+c.delta+'s';
    const localTag = c.local_edit ? ' · <span style="color:#c8843f">本地已修改</span>' : '';
    b.innerHTML=`${c.current?'● ':''}${c.name} · ${c.artist} · ${mm}:${ss} ${delta} · ${c.score}${localTag}`;
    if(!c.id){                       // 没有 id 的条目不可切换
      b.onclick=ev=>{ev.stopPropagation(); done('当前用的就是这条');};
      b.style.opacity='.6';
    }else b.onclick=async ev=>{ev.stopPropagation();
      if(S!==song || LRCEDIT){ box.remove(); return; }
      if(c.local_edit && c.current &&
         !confirm('这条歌词你本地改过。用网上的原版覆盖吗？（覆盖前会备份，可用「恢复最初」找回）')) return;
      box.remove();
      busy('换歌词中…');
      try{
        const r=await fetch('/api/pick',{method:'POST',headers:{'Content-Type':'application/json'},
          body: JSON.stringify({action:'pick', idx:song.idx, id:c.id})});
        const d=await r.json();
        if(!r.ok || !d.ok){ done(d.error||'换歌词失败'); return; }
        if(S!==song || LRCEDIT) return;
        await load(d.idx || song.idx);        // 重新拉这一首（已换新歌词）
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
