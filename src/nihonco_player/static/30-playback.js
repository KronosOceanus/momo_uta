/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
const CFG=(window.__CFG)||{};
const UI=(CFG.player&&CFG.player.ui)||{};
const PL=CFG.player||{};
// 播放器 · 统一播放层与播放条
function markPlaying(){
  document.querySelectorAll('.it').forEach(x=>{
    x.dataset.playing = (String(x.dataset.u)===String(NH.PLAYING_UID)) ? '1' : ''; });
}
function syncPlayControls(){
  const on = NH.PLAYING_UID !== null && NH.PLAYING_UID !== undefined;
  ['prev','play','next','loop','songloop','play2','back10','fwd10'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.disabled=!on;
  });
  const seek=document.getElementById('seek'); if(seek) seek.classList.toggle('off', !on);
}
function syncLoopBtn(){
  const b=document.getElementById('loop'); if(!b) return;
  b.textContent = NH.loop ? '单句循环：开' : '单句循环';
  b.classList.toggle('on', NH.loop);
}
function closeLineLoop(){
  if(!NH.loop) return;
  NH.loop=false; NH.LOOP_ROW=-1; syncLoopBtn();
}
NH.closeLineLoop = closeLineLoop;
NH.syncPlayControls = syncPlayControls;

function commitAudio(){
  if(!NH.S) return;
  const prev=NH.PLAYING_UID;
  if(prev!==null && prev!==undefined && String(prev)!==String(NH.S.uid)) closeLineLoop();
  NH.PLAYING_UID = NH.S.uid; markPlaying();
  NH.au.src = NH.S.audio || ('/audio/'+encodeURIComponent(NH.S.uid));
  NH.au.preload().catch(()=>{});          // 整首解码进内存：之后跳转没有解码器 flush
  NH.paintTicks?.();                      // src 切换后旧时长/旧歌词不能留着
  document.getElementById('ttl').textContent = '▶ ' + NH.S.title + (NH.S.artist?' · '+NH.S.artist:'');
  syncPlayBtn(); syncPlayControls();
}
// ── 统一播放层：普通视图与编辑表格共用同一套时间语义 ──
const META_RE=/^(作词|作曲|编曲|制作|演唱|歌\s*[:：]|Lyrics|Composer|Arranger|Producer)/;
function viewLines(){ return NH.VIEW_MODE==='lrc' ? NH.EROWS : NH.LINES; }
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
  return onceEvent('loadedmetadata', UI.canplay_wait_ms||900);
}
NH.SEEK_SEQ = 0; NH.SEEK_WAS_PLAYING = false;
async function seekPrecise(t){
  t=Math.max(0, t);
  if(NH.SEEK_SEQ===0) NH.SEEK_WAS_PLAYING=!NH.au.paused;   // 连点时以第一次的状态为准
  const seq=++NH.SEEK_SEQ;
  if(NH.SEEK_WAS_PLAYING) NH.au.pause();         // 画面与旧声音都在此停下
  await audioReady();
  if(seq!==NH.SEEK_SEQ) return;
  const seeked=onceEvent('seeked', UI.canplay_wait_ms||900);
  NH.au.currentTime=t;
  paintTransport();
  await seeked;
  if(seq!==NH.SEEK_SEQ) return;
  if(NH.au.readyState<3) await onceEvent('canplay', UI.canplay_wait_ms||900);
  if(seq!==NH.SEEK_SEQ) return;
  if(NH.SEEK_WAS_PLAYING) await NH.au.play().catch(()=>{});
  paintTransport();
  NH.SEEK_SEQ=0;                              // 这一轮结束，下一次重新取播放状态
}

function seekIdx(i, keepPlaying){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.PLAYING_UID!==NH.S.uid) commitAudio();
  const t=Math.max(0, lineT(l));
  seekPrecise(t);                              // 是否续播由 seekPrecise 自己判断
  highlight(i);
  if(NH.loop && !isMetaLine(viewLines()[i])) NH.LOOP_ROW=i;
  if(NH.VIEW_MODE==='lrc'){ NH.ESEL=i; NH.SEL.clear(); NH.paintSelection(); }
}
function selectLine(i){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.S && String(NH.PLAYING_UID) === String(NH.S.uid)){
    seekIdx(i, true);                   // 正在播这首：跳转，保持播放/暂停状态
  }else{
    NH.WMARK[NH.S.uid]=lineT(l);        // 查看另一首：只移动波形头
    highlight(i);                       // 只高亮，不碰音频
  }
}

async function playLine(i){
  if(!NH.S) return;
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  NH.WMARK[NH.S.uid]=lineT(l);
  if(NH.PLAYING_UID!==NH.S.uid) NH.commitAudio();
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
  if(NH.VIEW_MODE==='lrc'){
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
  if(NH.VIEW_MODE==='lrc'){
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
  if(!NH.S || String(NH.PLAYING_UID) !== String(NH.S.uid)) return;
  const t=NH.au.currentTime;
  const i=idxAt(t);
  if(i>=0){
    // 只在"索引变了"或"DOM 上确实没亮"时重绘（后者修 UI 被重建后不重画的问题）
    const el=NH.VIEW_MODE==='lrc' ? document.querySelector(`.lerow[data-i="${i}"]`)
                     : document.querySelectorAll('.ln')[i];
    const lit=NH.VIEW_MODE==='lrc' ? (el && el.classList.contains('cur'))
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
  document.getElementById('play2ico').textContent = NH.au.paused ? '▶' : '⏸';
  document.getElementById('mute').textContent = NH.au.muted||NH.au.volume===0 ? '🔇' : '🔊';
}
function paintTicks(){
  const box=document.getElementById('ticks'); box.innerHTML='';
  // 只有正在查看的歌就是正在播放的歌，竖线才有意义。
  if(!NH.S || NH.PLAYING_UID===null || NH.PLAYING_UID===undefined
     || String(NH.PLAYING_UID)!==String(NH.S.uid)) return;
  const dur=isFinite(NH.au.duration)?NH.au.duration:0; if(!dur) return;
  // LRC 模式下 EROWS 才是正在编辑的歌词；普通模式读播放行。
  const rows=NH.VIEW_MODE==='lrc' ? (NH.EROWS||[]) : (NH.LINES||[]);
  const frag=document.createDocumentFragment();
  rows.forEach(l=>{
    if(!l || l.t==null) return;
    const i=document.createElement('i');
    i.style.left=(l.t/dur*100)+'%';
    frag.appendChild(i);
  });
  box.appendChild(frag);
}
function seekToClientX(x){
  if(NH.PLAYING_UID===null) return;
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
  document.getElementById('play2').onclick=togglePlayPause;
  document.getElementById('back10').onclick=()=>{ if(NH.PLAYING_UID===null) return; seekPrecise(Math.max(0, NH.au.currentTime-10)); };
  document.getElementById('fwd10').onclick=()=>{ if(NH.PLAYING_UID===null) return; seekPrecise(Math.min(NH.au.duration||0, NH.au.currentTime+10)); };
  document.getElementById('volume').oninput=e=>{ NH.au.volume=+e.target.value; NH.au.muted=NH.au.volume===0; paintTransport(); };
  document.getElementById('mute').onclick=()=>{ NH.au.muted=!NH.au.muted; paintTransport(); };
  ['timeupdate','loadedmetadata','durationchange','play','pause','volumechange'].forEach(ev=>
    NH.au.addEventListener(ev, ()=>{ paintTransport(); if(ev==='loadedmetadata') paintTicks(); }));
})();

(function initRate(){
  const el=document.getElementById('rate');
  if(!el) return;
  el.min=PL.speed_min ?? 0.5;
  el.max=PL.speed_max ?? 1.25;
  el.step=PL.speed_step ?? 0.05;
  const v=Math.min(+el.max, Math.max(+el.min, +el.value||1));
  el.value=v; if(typeof el.dispatchEvent==='function') el.dispatchEvent(new Event('input'));
})();
const playBtn=document.getElementById('play');
let TOGGLE_AT=0;
function togglePlayPause(){
  const now=performance.now();
  if(now-TOGGLE_AT<(UI.toggle_debounce_ms||320)) return;              // 防止 pointerdown + click 连发
  TOGGLE_AT=now;
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  if(NH.au.paused) NH.au.play().catch(()=>{});
  else NH.au.pause();
}
function syncPlayBtn(){ playBtn.textContent = NH.au.paused ? '播放' : '暂停'; }
function playFromStart(){
  const song = NH.S;
  if(!song) return;
  const uid = song.uid;
  NH.au.preload().then(() => {
    if(!NH.S || String(NH.S.uid)!==String(uid)) return;
    NH.au.currentTime = 0;
    NH.au.play().catch(()=>{});
  }).catch(()=>{});
}
NH.playFromStart = playFromStart;
document.getElementById('start').onclick=()=>{ if(!NH.S) return; commitAudio(); playFromStart(); };
playBtn.onclick=togglePlayPause;
document.getElementById('play2').addEventListener('pointerdown', e=>{
  if(e.pointerType==='mouse' || e.pointerType==='touch'){
    e.preventDefault();
    togglePlayPause();
  }
});
['play','pause','emptied','loadstart','ended','waiting'].forEach(ev=>NH.au.addEventListener(ev, syncPlayBtn));
['pause','seeked','loadedmetadata'].forEach(ev=>NH.au.addEventListener(ev, ()=>{ if(typeof NH.WAVE!=='undefined' && NH.WAVE && NH.VIEW_MODE==='lrc') NH.drawWave(); }));
NH.au.addEventListener('play', syncPlayBtn); NH.au.addEventListener('pause', syncPlayBtn);
document.getElementById('rate').oninput=e=>{NH.au.playbackRate=+e.target.value;document.getElementById('rv').textContent=(+e.target.value).toFixed(2)+'×';};
async function stepPlaying(dir){
  if(NH.PLAYING_UID===null) return;
  if(!NH.isSelfPlaying()){
    const ok=await NH.load(NH.PLAYING_UID, false);   // 页面跳到 A，不打断 A
    if(!ok) return;
  }
  const n=nextIdx(dir); if(n!==null) seekIdx(n,true);
}
document.getElementById('prev').onclick=()=>stepPlaying(-1);
document.getElementById('next').onclick=()=>stepPlaying(1);
document.getElementById('t-rm').onclick=e=>{NH.MODE='rm';e.target.classList.add('on');document.getElementById('t-ky').classList.remove('on');const l=NH.LINES[NH.CUR];NH.renderSide();};
document.getElementById('t-ky').onclick=e=>{NH.MODE='ky';e.target.classList.add('on');document.getElementById('t-rm').classList.remove('on');const l=NH.LINES[NH.CUR];NH.renderSide();};
document.getElementById('rem').onclick=async()=>{
  if(!NH.S || NH.BUSY) return;
  if(NH.VIEW_MODE==='lrc' && !await NH.load(NH.S.uid, false, 'normal')) return;
  const song=NH.S;
  document.querySelectorAll('.menu').forEach(m=>m.remove());
  NH.busy('匹配中…'); NH.lock(this, true);
  let d;
  try{
    d = await NH.api('/api/rematch',{action:'rematch', uid:song.uid,
      duration:(song.duration || (NH.isSelfPlaying()?NH.au.duration:0))});
  }catch(err){
    NH.done('匹配失败：'+err.message); NH.lock(null,false); return;
  }
  if(NH.S!==song || NH.VIEW_MODE==='lrc'){ NH.lock(null,false); return; }
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
      if(NH.S!==song || NH.VIEW_MODE==='lrc'){ box.remove(); return; }
      box.remove();
      NH.busy('换歌词中…');
      try{
        const d=await NH.api('/api/pick',{action:'pick', uid:song.uid, id:c.id});
        if(!d.ok){ NH.done(d.error||'换歌词失败'); return; }
        if(NH.S!==song || NH.VIEW_MODE==='lrc') return;
        NH.NO_MATCH.delete(String(d.uid || song.uid));
        await NH.load(d.uid || song.uid);        // 重新拉这一首（已换新歌词）
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
document.getElementById('loop').onclick=async()=>{
  if(NH.PLAYING_UID===null) return;
  if(!NH.isSelfPlaying()){
    const ok=await NH.load(NH.PLAYING_UID, false);
    if(!ok) return;
  }
  NH.loop=!NH.loop;
  if(NH.loop){
    const items=navItems();
    const cur=idxAt(NH.au.currentTime);
    const hit=items.find(x=>x.i>=cur) || items[0];
    NH.LOOP_ROW = hit? hit.i : -1;
  }
  syncLoopBtn();
};

// ── 单曲循环：播完自动从头再播 ──────────────────
NH.loopSong = true;
const songLoopBtn = document.getElementById('songloop');
function syncSongLoop(){
  if(!songLoopBtn) return;
  songLoopBtn.textContent = '单曲循环：' + (NH.loopSong ? '开' : '关');
  songLoopBtn.classList.toggle('on', NH.loopSong);
}
if(songLoopBtn) songLoopBtn.onclick = () => {
  if(NH.PLAYING_UID===null) return;          // 只切播放器状态，不跳回 A
  NH.loopSong = !NH.loopSong; syncSongLoop();
};
syncSongLoop(); syncLoopBtn(); syncPlayControls();
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

Object.assign(NH, {markPlaying, commitAudio, syncPlayControls, META_RE, viewLines, lineT, isMetaLine, idxAt, navItems, onceEvent, audioReady, seekPrecise, seekIdx, selectLine, playLine, nextIdx, rowForTime, highlight, seek, paint, fmtTime, paintTransport, paintTicks, seekToClientX, PL, playBtn, syncPlayBtn, stepPlaying});
})();
