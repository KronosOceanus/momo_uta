/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
// 播放器 · 统一播放层与播放条
function markPlaying(){
  document.querySelectorAll('.it').forEach(x=>{
    x.dataset.playing = (String(x.dataset.i)===String(NH.PLAYING)) ? '1' : ''; });
}
function commitAudio(){
  if(!NH.S) return;
  NH.PLAYING = NH.S.idx; markPlaying();
  NH.au.src = NH.S.audio || ('/audio/'+NH.S.idx);
  NH.au.preload().catch(()=>{});          // 整首解码进内存：之后跳转没有解码器 flush
  document.getElementById('ttl').textContent = '▶ ' + NH.S.title + (NH.S.artist?' · '+NH.S.artist:'');
  syncPlayBtn();
}
// ── 统一播放层：普通视图与编辑表格共用同一套时间语义 ──
const META_RE=/^(作词|作曲|编曲|制作|演唱|歌\s*[:：]|Lyrics|Composer|Arranger|Producer)/;
function viewLines(){ return NH.LRCEDIT ? NH.EROWS : NH.LINES; }
function lineT(l){ return (l && l.t!==null && l.t!==undefined) ? l.t+NH.OFFSET : null; }
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
    const fin=()=>{ if(done) return; done=true; NH.au.removeEventListener(name, fin); res(); };
    NH.au.addEventListener(name, fin); setTimeout(fin, ms);
  });
}
function audioReady(){
  if(NH.au.readyState>=1 && isFinite(NH.au.duration)) return Promise.resolve();
  return onceEvent('loadedmetadata', 900);
}
NH.SEEK_SEQ = 0; NH.SEEK_WAS_PLAYING = false;
async function seekPrecise(t){
  t=Math.max(0, t);
  if(NH.SEEK_SEQ===0) NH.SEEK_WAS_PLAYING=!NH.au.paused;   // 连点时以第一次的状态为准
  const seq=++NH.SEEK_SEQ;
  if(NH.SEEK_WAS_PLAYING) NH.au.pause();         // 画面与旧声音都在此停下
  await audioReady();
  if(seq!==NH.SEEK_SEQ) return;
  const seeked=onceEvent('seeked', 900);
  NH.au.currentTime=t;
  paintTransport();
  await seeked;
  if(seq!==NH.SEEK_SEQ) return;
  if(NH.au.readyState<3) await onceEvent('canplay', 900);
  if(seq!==NH.SEEK_SEQ) return;
  if(NH.SEEK_WAS_PLAYING) await NH.au.play().catch(()=>{});
  paintTransport();
  NH.SEEK_SEQ=0;                              // 这一轮结束，下一次重新取播放状态
}

function seekIdx(i, keepPlaying){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.PLAYING!==NH.S.idx) commitAudio();
  const t=Math.max(0, lineT(l));
  seekPrecise(t);                              // 是否续播由 seekPrecise 自己判断
  highlight(i);
  if(NH.loop && !isMetaLine(viewLines()[i])) NH.LOOP_ROW=i;
  if(NH.LRCEDIT){ NH.ESEL=i; NH.SEL.clear(); NH.paintSelection(); }
}
function selectLine(i){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.S && String(NH.PLAYING) === String(NH.S.idx)){
    seekIdx(i, true);                   // 正在播这首：跳转，保持播放/暂停状态
  }else{
    highlight(i);                       // 只是查看另一首：只高亮，不碰音频
  }
}

async function playLine(i){
  if(!NH.S) return;
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.PLAYING!==NH.S.idx) NH.commitAudio();
  await seekPrecise(Math.max(0, lineT(l)));
  await NH.au.play().catch(()=>{});
  highlight(i);
}

function nextIdx(dir){
  const items=navItems(); if(!items.length) return null;
  const i=idxAt(NH.au.currentTime);
  let at=items.findIndex(x=>x.i===i);
  if(at<0){                       // 不在任何行上：按时间找最近位置
    const t=NH.au.currentTime;
    at = dir>0 ? items.findIndex(x=>x.t> t) : items.length-1;
    if(at<0) at = dir>0 ? items.length-1 : 0;
  }
  const to = at + (dir>0?1:-1);
  if(to<0 || to>=items.length) return items[dir>0?at:0].i;
  return items[to].i;
}
function rowForTime(t){
  let n=-1;
  for(let i=0;i<NH.EROWS.length;i++){ const tt=NH.EROWS[i].t; if(tt!==null && tt<=t) n=i; }
  return n<0?0:n;
}
function highlight(i){
  const ls=viewLines(); const l=ls[i];
  NH.CUR=i;
  if(NH.LRCEDIT){
    document.querySelectorAll('.lerow').forEach(el=>
      el.classList.toggle('cur', +el.dataset.i===i));
    // 播放中不自动滚动表格：换行时滚动正是"画面顿一下"的可疑来源
    if(!NH.SEL.size && NH.au.paused)
      document.querySelector(`.lerow[data-i="${i}"]`)?.scrollIntoView({block:'nearest'});
  }else{
    document.querySelectorAll('.ln').forEach((el,k)=>el.classList.toggle('on', k===i && !isMetaLine(ls[k])));
    document.querySelectorAll('.ln')[i]?.scrollIntoView({block:'center'});
  }
  // 播放时 rAF 循环已在画波形，这里不再重复画
  // 右侧罗马音：编辑模式下按行号对齐（编辑后的文本与右侧同源），普通模式按时间
  if(NH.LRCEDIT){
    // 右侧罗马音在编辑模式下隐藏，不需要联动
  }else{
    NH.paint2(i);          // 右侧只跟随"当前行"；meta 区间两边都不亮
  }
}
function seek(n){ seekIdx(n, true); }
function paint(n){
  if(n===NH.CUR) return;
  highlight(n);
}
NH.au.onloadedmetadata=()=>{
  if(!NH.LINES.length) return;
  const last=NH.LINES[NH.LINES.length-1].t;
  if(NH.au.duration && last>0 && last/NH.au.duration<0.7){
    document.getElementById('ttl').textContent += `　⚠ 歌词只覆盖到 ${Math.round(last/NH.au.duration*100)}%`;
  }
};
NH.LRC_CUR = -1;
NH.LOOP_ROW = -1;

NH.au.ontimeupdate=()=>{
  if(!NH.S || String(NH.PLAYING) !== String(NH.S.idx)) return;
  const t=NH.au.currentTime;
  const i=idxAt(t);
  if(i>=0){
    // 只在"索引变了"或"DOM 上确实没亮"时重绘（后者修 UI 被重建后不重画的问题）
    const el=NH.LRCEDIT ? document.querySelector(`.lerow[data-i="${i}"]`)
                     : document.querySelectorAll('.ln')[i];
    const lit=NH.LRCEDIT ? (el && el.classList.contains('cur'))
                      : (el && el.classList.contains('on'));
    if(i!==NH.CUR || !lit) highlight(i);
  }
  if(NH.loop && NH.LOOP_ROW>=0){              // 单句循环：锚定开启时的那一行
    const items=navItems();
    const at=items.findIndex(x=>x.i===NH.LOOP_ROW);
    if(at>=0){
      const start=items[at].t;
      const end=(at+1<items.length)? items[at+1].t : start+8;
      if(t>=end){ NH.au.currentTime=start; highlight(NH.LOOP_ROW); }
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
  const dur=isFinite(NH.au.duration)?NH.au.duration:0;
  const cur=NH.au.currentTime||0;
  document.getElementById('tcur').textContent=fmtTime(cur);
  document.getElementById('tdur').textContent=fmtTime(dur);
  const pct=dur?Math.min(100, cur/dur*100):0;
  document.getElementById('fill').style.width=pct+'%';
  document.getElementById('thumb').style.left=pct+'%';
  document.getElementById('play2').textContent = NH.au.paused ? '▶' : '⏸';
  document.getElementById('mute').textContent = NH.au.muted||NH.au.volume===0 ? '🔇' : '🔊';
}
function paintTicks(){
  const box=document.getElementById('ticks'); box.innerHTML='';
  const dur=isFinite(NH.au.duration)?NH.au.duration:0; if(!dur) return;
  const frag=document.createDocumentFragment();
  (NH.LINES||[]).forEach(l=>{
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
  const dur=isFinite(NH.au.duration)?NH.au.duration:0;
  if(dur) NH.au.currentTime=ratio*dur;
  paintTransport();
}
(function bindTransport(){
  const seek=document.getElementById('seek');
  let dragging=false;
  seek.addEventListener('mousedown', e=>{ dragging=true; seekToClientX(e.clientX); });
  document.addEventListener('mousemove', e=>{ if(dragging) seekToClientX(e.clientX); });
  document.addEventListener('mouseup', ()=>{ dragging=false; });
  document.getElementById('play2').onclick=()=>{ if(NH.au.paused) NH.au.play().catch(()=>{}); else NH.au.pause(); };
  document.getElementById('back10').onclick=()=>{ seekPrecise(Math.max(0, NH.au.currentTime-10)); };
  document.getElementById('fwd10').onclick=()=>{ seekPrecise(Math.min(NH.au.duration||0, NH.au.currentTime+10)); };
  document.getElementById('volume').oninput=e=>{ NH.au.volume=+e.target.value; NH.au.muted=NH.au.volume===0; paintTransport(); };
  document.getElementById('mute').onclick=()=>{ NH.au.muted=!NH.au.muted; paintTransport(); };
  ['timeupdate','loadedmetadata','durationchange','play','pause','volumechange'].forEach(ev=>
    NH.au.addEventListener(ev, ()=>{ paintTransport(); if(ev==='loadedmetadata') paintTicks(); }));
})();

const PL=(window.__CFG&&window.__CFG.player)||{};
(function initRate(){
  const el=document.getElementById('rate');
  if(!el) return;
  el.min=PL.speed_min ?? 0.5;
  el.max=PL.speed_max ?? 1.25;
  el.step=0.05;
  const v=Math.min(+el.max, Math.max(+el.min, +el.value||1));
  el.value=v; if(typeof el.dispatchEvent==='function') el.dispatchEvent(new Event('input'));
})();
const playBtn=document.getElementById('play');
function syncPlayBtn(){ playBtn.textContent = NH.au.paused ? '播放' : '暂停'; }
document.getElementById('start').onclick=()=>{ if(!NH.S) return; commitAudio(); NH.au.play().catch(()=>{}); };
playBtn.onclick=()=>{
  if(NH.S && NH.PLAYING!==NH.S.idx){ commitAudio(); NH.au.play().catch(()=>{}); return; }
  if(NH.au.paused){ NH.au.play().catch(()=>{}); } else { NH.au.pause(); }
};
['play','pause','emptied','loadstart','ended','waiting'].forEach(ev=>NH.au.addEventListener(ev, syncPlayBtn));
['pause','seeked','loadedmetadata'].forEach(ev=>NH.au.addEventListener(ev, ()=>{ if(typeof NH.WAVE!=='undefined' && NH.WAVE && NH.LRCEDIT) NH.drawWave(); }));
NH.au.addEventListener('play', syncPlayBtn); NH.au.addEventListener('pause', syncPlayBtn);
document.getElementById('rate').oninput=e=>{NH.au.playbackRate=+e.target.value;document.getElementById('rv').textContent=(+e.target.value).toFixed(2)+'×';};
document.getElementById('prev').onclick=()=>{ const n=nextIdx(-1); if(n!==null) seekIdx(n,true); };
document.getElementById('next').onclick=()=>{ const n=nextIdx(1);  if(n!==null) seekIdx(n,true); };
document.getElementById('t-rm').onclick=e=>{NH.MODE='rm';e.target.classList.add('on');document.getElementById('t-ky').classList.remove('on');const l=NH.LINES[NH.CUR];NH.renderSide();};
document.getElementById('t-ky').onclick=e=>{NH.MODE='ky';e.target.classList.add('on');document.getElementById('t-rm').classList.remove('on');const l=NH.LINES[NH.CUR];NH.renderSide();};
document.getElementById('rem').onclick=async()=>{
  if(!NH.S || NH.BUSY) return;
  if(NH.LRCEDIT && !await NH.load(NH.S.idx, false, false)) return;
  const song=NH.S;
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  NH.busy('匹配中…'); NH.lock(this, true);
  let d;
  try{
    const r = await fetch('/api/rematch',{method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'rematch', idx:song.idx, duration:(NH.au.duration||0)})});
    d = await r.json();
  }catch(err){
    NH.done('匹配失败：'+err.message); NH.lock(null,false); return;
  }
  if(NH.S!==song || NH.LRCEDIT){ NH.lock(null,false); return; }
  if(!d.candidates || !d.candidates.length){ NH.done('没找到候选，可以试试手动导入 lrc'); NH.lock(null,false); return; }
  NH.done(`找到 ${d.candidates.length} 个候选`); NH.lock(null,false);
  const box=document.createElement('div'); box.className='menu'; box.style.maxWidth='520px';
  box.innerHTML='<div style="font-size:12px;color:#878c95;padding:4px 8px">选一个（分数越高越可能是同一版）· 候选来自网络，不读本地缓存</div>';
  d.candidates.forEach(c=>{
    const b=document.createElement('button');
    const mm=Math.floor(c.duration/60), ss=String(Math.round(c.duration%60)).padStart(2,'0');
    const delta=(c.delta===null||c.delta===undefined)?'' : (c.delta>=0?'+':'')+c.delta+'s';
    b.innerHTML=`${c.current?'● ':''}${c.name} · ${c.artist} · ${mm}:${ss} ${delta} · ${c.score}`;
    if(!c.id){                       // 没有 id 的条目不可切换
      b.onclick=ev=>{ev.stopPropagation(); NH.done('当前用的就是这条');};
      b.style.opacity='.6';
    }else b.onclick=async ev=>{ev.stopPropagation();
      if(NH.S!==song || NH.LRCEDIT){ box.remove(); return; }
      box.remove();
      NH.busy('换歌词中…');
      try{
        const r=await fetch('/api/pick',{method:'POST',headers:{'Content-Type':'application/json'},
          body: JSON.stringify({action:'pick', idx:song.idx, id:c.id})});
        const d=await r.json();
        if(!r.ok || !d.ok){ NH.done(d.error||'换歌词失败'); return; }
        if(NH.S!==song || NH.LRCEDIT) return;
        await NH.load(d.idx || song.idx);        // 重新拉这一首（已换新歌词）
        NH.loadLib();
        NH.done(`已换成 ${c.name}（${d.lines} 行歌词）`);
      }catch(err){ NH.done('换歌词失败：'+err.message); }
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
document.getElementById('loop').onclick=e=>{NH.loop=!NH.loop;e.target.classList.toggle('on',NH.loop);
  if(NH.loop){
    const items=navItems();
    const cur=idxAt(NH.au.currentTime);
    const hit=items.find(x=>x.i>=cur) || items[0];
    NH.LOOP_ROW = hit? hit.i : -1;
  }
  e.target.textContent = NH.loop ? '单句循环：开' : '单句循环';};

// ── 单曲循环：播完自动从头再播 ──────────────────
NH.loopSong = true;
const songLoopBtn = document.getElementById('songloop');
function syncSongLoop(){
  if(!songLoopBtn) return;
  songLoopBtn.textContent = '单曲循环：' + (NH.loopSong ? '开' : '关');
  songLoopBtn.classList.toggle('on', NH.loopSong);
}
if(songLoopBtn) songLoopBtn.onclick = () => { NH.loopSong = !NH.loopSong; syncSongLoop(); };
syncSongLoop();
NH.au.addEventListener('ended', () => {
  if(!NH.loopSong) return;
  const song = NH.S;
  // 等引擎的 ended/pause 流程走完再起新 source，避免把 watch 循环覆盖
  setTimeout(() => {
    if(!song || NH.S !== song || !NH.loopSong) return;
    NH.au.currentTime = 0;
    NH.au.play().catch(()=>{});
  }, 0);
});

document.onkeydown=e=>{
  if(e.target.tagName==='INPUT' || e.isComposing || e.keyCode===229) return;
  if(e.code==='Space'){e.preventDefault();NH.au.paused?NH.au.play():NH.au.pause();}
  if(e.code==='ArrowLeft')document.getElementById('prev').click();
  if(e.code==='ArrowRight')document.getElementById('next').click();
};

Object.assign(NH, {markPlaying, commitAudio, META_RE, viewLines, lineT, isMetaLine, idxAt, navItems, onceEvent, audioReady, seekPrecise, seekIdx, selectLine, playLine, nextIdx, rowForTime, highlight, seek, paint, fmtTime, paintTransport, paintTicks, seekToClientX, PL, playBtn, syncPlayBtn});
})();
