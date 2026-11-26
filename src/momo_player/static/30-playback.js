/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
let stBusy = false;
let stQueued = false;
let stToken = 0;
let stWantSpeed = null;
let stWantKey = null;
NH.ST_KEY = NH.ST_KEY || 0;
const KEY_MIN = -6, KEY_MAX = 6;
const SPEED_VALUES = [1.25, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5];
const CFG=(window.__CFG)||{};
const UI=(CFG.player&&CFG.player.ui)||{};
const PL=CFG.player||{};
const TOGGLE_DEBOUNCE_MS = 320;
// 播放器 · 统一播放层与播放条
function markPlaying(){
  document.querySelectorAll('.it').forEach(x=>{
    x.dataset.playing = (String(x.dataset.u)===String(NH.PLAYING_UID)) ? '1' : ''; });
}
function syncPlayControls(){
  const on = NH.PLAYING_UID !== null && NH.PLAYING_UID !== undefined;
  ['prev','next','loop','play2','back10','fwd10'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.disabled=!on;
  });
  const seek=document.getElementById('seek'); if(seek) seek.classList.toggle('off', !on);
}
function syncLoopBtn(){
  const b=document.getElementById('loop'); if(!b) return;
  b.textContent = '单句循环：' + (NH.loop ? '开' : '关');
  b.classList.toggle('on', NH.loop);
}
function closeLineLoop(){
  if(!NH.loop) return;
  NH.loop=false; NH.LOOP_ROW=-1; syncLoopBtn();
}
NH.closeLineLoop = closeLineLoop;
NH.syncPlayControls = syncPlayControls;

function findSongItem(uid){
  const u=String(uid);
  for(const g of (NH.PLS||[])){
    for(const it of (g.items||[])){
      if(String(it.uid)===u) return it;
    }
  }
  for(const it of (NH.LIB||[])){
    if(String(it.uid)===u) return it;
  }
  return null;
}

function fallbackToOriginal(song, stSrc){
  if(!stSrc || !NH.ST_ON) return;
  if(String(NH.PLAYING_UID)!==String(song.uid)) return;
  if(String(NH.ST_UID)!==String(song.uid)) return;
  const speed=NH.ST_SPEED;
  NH.reportClientError?.('soundtouch_preload',
    `processed audio failed uid=${song.uid} speed=${speed}`, '', {speed});
  cancelSoundTouch(song.uid);
  setSpeedUI(1, false);
  setKeyUI(0, false);
  NH.au.src=song.audio || ('/audio/'+encodeURIComponent(song.uid));
  NH.au.playbackRate=1;
  NH.au.preload().catch(()=>{});
  NH.done('变速文件不可用，已回到原曲');
}

function commitAudio(song){
  song = song || NH.S;
  if(!song) return;
  const prev=NH.PLAYING_UID;
  if(prev!==null && prev!==undefined && String(prev)!==String(song.uid)) closeLineLoop();
  NH.track('seek'); NH.track('lineplay');
  NH.SEEK_ACTIVE = false; NH.SEEK_WAS_PLAYING = false;
  const switched = prev !== null && prev !== undefined
    && String(prev) !== String(song.uid);
  if(switched) resetSpeedTo1();
  if(NH.ST_ON && String(NH.ST_UID)!==String(song.uid)) cancelSoundTouch();
  NH.PLAYING_UID = song.uid;
  NH.PLAY_ITEM = song;
  markPlaying();
  const stSrc = NH.ST_ON && NH.ST_URL && String(NH.ST_UID)===String(song.uid);
  NH.au.src = stSrc ? NH.ST_URL : (song.audio || ('/audio/'+encodeURIComponent(song.uid)));
  // SoundTouch 已经把速度写进文件；这里必须回到 1.0，否则会二次降速变调。
  const rateEl = document.getElementById('rate');
  const wantSpeed = +(rateEl && rateEl.value) || 1;
  NH.au.playbackRate = 1;
  const wantKey = NH.ST_KEY || 0;
  const pending = !stSrc && (wantSpeed !== 1 || wantKey !== 0)
    && !stBusy && !stQueued;
  if(pending) stQueued=true;
  // 先等音频真正 preload 完成，再套用待处理的 speed/key；否则新歌刚开播时
  // seekPlayback 会在 loadedmetadata 之前失败，产生假的“生成失败”toast。
  NH.au.preload().then(()=>{
    if(!pending) return;
    stQueued=false;
    if(String(NH.PLAYING_UID)!==String(song.uid) || stBusy) return;
    const now=+(rateEl && rateEl.value) || 1;
    applyTransform(now, NH.ST_KEY || 0);
  }).catch(()=>{
    if(pending) stQueued=false;
    fallbackToOriginal(song, stSrc);
  });  // 整首解码进内存：之后跳转没有解码器 flush
  NH.paintTicks?.();                      // src 切换后旧时长/旧歌词不能留着
  document.getElementById('ttl').textContent = '▶ ' + song.title + (song.artist?' · '+song.artist:'');
  syncPlayBtn(); syncPlayControls();
  syncBackPlaying();
}

function playTarget(uid){
  const item = findSongItem(uid);
  if(!item){
    NH.done?.('歌曲不可用');
    return false;
  }
  commitAudio(item);
  playFromStart(item);
  return true;
}

function syncBackPlaying(){
  const b=document.getElementById('backplaying');
  if(!b) return;
  const diff = NH.PLAYING_UID !== null && NH.PLAYING_UID !== undefined
    && NH.PLAY_ITEM && NH.S
    && String(NH.PLAYING_UID) !== String(NH.S.uid);
  b.hidden = !diff;
}

// ── 统一播放层
// ── 统一播放层：普通视图与编辑表格共用同一套时间语义 ──
const META_RE=/^(作词|作曲|编曲|制作|演唱|歌\s*[:：]|Lyrics|Composer|Arranger|Producer)/;
function viewLines(){ return NH.VIEW_MODE==='lrc' ? NH.EROWS : NH.LINES; }
function lineT(l){ return (l && l.t!==null && l.t!==undefined) ? l.t+NH.OFFSET : null; }
function isMetaLine(l){ return !l || l.meta || META_RE.test((l.text||'').trim()); }
function idxAt(t){
  t = NH.sourceTime(t);
  const ls=viewLines(); let n=-1;
  for(let i=0;i<ls.length;i++){
    const tt=lineT(ls[i]);
    // meta 行不参与播放高亮；否则播放到 meta 区间时
    // 每帧都 highlight 它，会把用户滚动拉回开头。
    if(tt!==null && !isMetaLine(ls[i]) && tt<=t) n=i;
  }
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
NH.SEEK_ACTIVE = false; NH.SEEK_WAS_PLAYING = false;
async function ensureAudioLoaded(){
  if(typeof NH.au.preload!=='function') return true;
  try{
    await NH.au.preload();
    return true;
  }catch(e){
    NH.reportClientError?.('audio_preload', e.message, e.stack);
    return false;
  }
}
async function seekPrecise(t){
  const song = NH.S;
  if(!song) return false;
  const uid = String(song.uid);
  t=Math.max(0, t);
  if(!NH.SEEK_ACTIVE){ NH.SEEK_WAS_PLAYING=!NH.au.paused; NH.SEEK_ACTIVE=true; }
  const seq=NH.track('seek');
  const current = () => NH.isCurrent('seek', seq)
    && NH.S && String(NH.S.uid) === uid
    && String(NH.PLAYING_UID) === uid;
  try {
    if(NH.SEEK_WAS_PLAYING) NH.au.pause();         // 画面与旧声音都在此停下
    if(!await ensureAudioLoaded()) return false;
    if(!current()) return false;
    await audioReady();
    if(!current()) return false;
    const seeked=onceEvent('seeked', UI.canplay_wait_ms||900);
    NH.au.currentTime=t;
    paintTransport();
    await seeked;
    if(!current()) return false;
    if(NH.au.readyState<3) await onceEvent('canplay', UI.canplay_wait_ms||900);
    if(!current()) return false;
    if(NH.SEEK_WAS_PLAYING) await NH.au.play().catch(()=>{});
    paintTransport();
    return true;
  } finally {
    if(NH.isCurrent('seek', seq)){
      NH.SEEK_ACTIVE=false;
      NH.SEEK_WAS_PLAYING=false;
    }
  }
}

async function seekPlayback(t){
  const uid = NH.PLAYING_UID;
  if(uid === null || uid === undefined) return false;
  t=Math.max(0, t);
  if(!NH.SEEK_ACTIVE){ NH.SEEK_WAS_PLAYING=!NH.au.paused; NH.SEEK_ACTIVE=true; }
  const seq=NH.track('seek');
  const current=()=>NH.isCurrent('seek', seq)
    && String(NH.PLAYING_UID) === String(uid);
  try {
    if(NH.SEEK_WAS_PLAYING) NH.au.pause();
    if(!await ensureAudioLoaded()) return false;
    if(!current()) return false;
    await audioReady();
    if(!current()) return false;
    const seeked=onceEvent('seeked', UI.canplay_wait_ms||900);
    NH.au.currentTime=t;
    paintTransport();
    await seeked;
    if(!current()) return false;
    if(NH.au.readyState<3) await onceEvent('canplay', UI.canplay_wait_ms||900);
    if(!current()) return false;
    if(NH.SEEK_WAS_PLAYING) await NH.au.play().catch(()=>{});
    paintTransport();
    return true;
  } finally {
    if(NH.isCurrent('seek', seq)){
      NH.SEEK_ACTIVE=false;
      NH.SEEK_WAS_PLAYING=false;
    }
  }
}

function seekIdx(i){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.PLAYING_UID!==NH.S.uid) commitAudio();
  const t=Math.max(0, lineT(l));
  seekPrecise(NH.audioTime(t));                              // 是否续播由 seekPrecise 自己判断
  highlight(i);
  if(NH.loop && !isMetaLine(viewLines()[i])) NH.LOOP_ROW=i;
  if(NH.VIEW_MODE==='lrc'){ NH.ESEL=i; NH.SEL.clear(); NH.paintSelection(); }
}
function selectLine(i){
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  if(NH.S && String(NH.PLAYING_UID) === String(NH.S.uid)){
    seekIdx(i);                         // 正在播这首：跳转，保持播放/暂停状态
  }else{
    NH.WMARK[NH.S.uid]=lineT(l);        // 查看另一首：只移动波形头
    highlight(i);                       // 只高亮，不碰音频
  }
}

async function playLine(i){
  if(!NH.S) return;
  const ls=viewLines(); const l=ls[i];
  if(!l || isMetaLine(l) || lineT(l)===null) return;
  const song = NH.S;
  NH.WMARK[song.uid]=lineT(l);
  if(String(NH.PLAYING_UID)!==String(song.uid)) NH.commitAudio();
  const seq=NH.track('lineplay');
  const ok=await seekPrecise(NH.audioTime(Math.max(0, lineT(l))));
  if(!ok || !NH.isCurrent('lineplay', seq) || NH.S !== song) return;
  await NH.au.play().catch(()=>{});
  if(!NH.isCurrent('lineplay', seq) || NH.S !== song) return;
  highlight(i);
}

function nextIdx(dir){
  const items=navItems(); if(!items.length) return null;
  const i=idxAt(NH.au.currentTime);
  const at=items.findIndex(x=>x.i===i);
  if(at<0) return items[0].i;              // 开头之前：上一句/下一句都停在第一句
  if(dir>0) return items[Math.min(at+1, items.length-1)].i;
  return items[Math.max(at-1, 0)].i;
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
    if(!isMetaLine(ls[i]))
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
function seek(n){ seekIdx(n); }
NH.au.onloadedmetadata=()=>{
  if(!NH.S || String(NH.PLAYING_UID)!==String(NH.S.uid)) return;
  if(!NH.LINES.length) return;
  const last=NH.LINES[NH.LINES.length-1].t;
  const sourceDur=NH.au.duration ? (NH.ST_ON ? NH.au.duration * NH.ST_SPEED : NH.au.duration) : 0;
  if(sourceDur && last>0 && last/sourceDur<0.7){
    document.getElementById('ttl').textContent += `　⚠ 歌词只覆盖到 ${Math.round(last/sourceDur*100)}%`;
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
      if(t>=NH.audioTime(end)){ NH.au.currentTime=NH.audioTime(start); highlight(NH.LOOP_ROW); }
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
    const at=lineT(l);
    if(at===null) return;
    const i=document.createElement('i');
    const pct=NH.audioTime(at)/dur*100;
    i.style.left=Math.max(0, Math.min(100, pct))+'%';
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
  document.getElementById('back10').onclick=()=>{ if(NH.PLAYING_UID===null) return; seekPlayback(Math.max(0, NH.au.currentTime-10)); };
  document.getElementById('fwd10').onclick=()=>{ if(NH.PLAYING_UID===null) return; seekPlayback(Math.min(NH.au.duration||0, NH.au.currentTime+10)); };
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
let TOGGLE_AT=0;
function togglePlayPause(){
  const now=performance.now();
  if(now-TOGGLE_AT<TOGGLE_DEBOUNCE_MS) return;              // 防止 pointerdown + click 连发
  TOGGLE_AT=now;
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  if(NH.au.paused) NH.au.play().catch(()=>{});
  else NH.au.pause();
}
function syncPlayBtn(){ const ico=document.getElementById('play2ico'); if(ico) ico.textContent = NH.au.paused ? '▶' : '⏸'; }
function playFromStart(song){
  song = song || NH.S;
  if(!song) return;
  const uid = song.uid;
  NH.au.preload().then(() => {
    if(!NH.PLAY_ITEM || String(NH.PLAY_ITEM.uid)!==String(uid)
       || String(NH.PLAYING_UID)!==String(uid)) return;
    NH.au.currentTime = 0;
    NH.au.play().catch(()=>{});
  }).catch(()=>{});
}
NH.playFromStart = playFromStart;
document.getElementById('start').onclick=()=>{ if(!NH.S) return; commitAudio(); playFromStart(); };
document.getElementById('play2').addEventListener('pointerdown', e=>{
  if(e.pointerType==='mouse' || e.pointerType==='touch'){
    e.preventDefault();
    togglePlayPause();
  }
});
['play','pause','emptied','loadstart','ended','waiting'].forEach(ev=>NH.au.addEventListener(ev, syncPlayBtn));
NH.au.addEventListener('error', ()=>{
  const song=NH.PLAY_ITEM;
  if(!song || NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  NH.reportClientError?.('audio_error',
    `uid=${song.uid} speed=${NH.ST_ON ? NH.ST_SPEED : 1}`, '', {uid:song.uid});
  NH.done('音频读取失败，请重试');
  syncPlayBtn();
  paintTransport();
});
['pause','seeked','loadedmetadata'].forEach(ev=>NH.au.addEventListener(ev, ()=>{ if(typeof NH.WAVE!=='undefined' && NH.WAVE && NH.VIEW_MODE==='lrc') NH.drawWave(); }));
NH.au.addEventListener('play', syncPlayBtn); NH.au.addEventListener('pause', syncPlayBtn);
function stSourcePos(){
  return NH.sourceTime(NH.au.currentTime || 0);
}
function playingSong(){
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return null;
  if(NH.PLAY_ITEM && String(NH.PLAY_ITEM.uid)===String(NH.PLAYING_UID)) return NH.PLAY_ITEM;
  return findSongItem(NH.PLAYING_UID);
}
function speedTarget(){
  return playingSong();
}
function cancelSoundTouch(uid){
  const hadWork=NH.ST_ON || stBusy || !!NH.ST_URL || !!NH.ST_UID
    || stWantSpeed!==null || stWantKey!==null || !!NH.ST_KEY;
  stToken++;
  stWantSpeed=null;
  stWantKey=null;
  stQueued=false;
  stBusy=false;
  const target=speedTarget();
  const cancelUid=uid || NH.ST_UID || (target && target.uid) || '';
  if(hadWork && cancelUid) NH.api('/api/soundtouch/cancel',{uid:String(cancelUid)}).catch(()=>{});
  NH.ST_ON=false; NH.ST_URL=null; NH.ST_UID=null; NH.ST_SPEED=1;
  NH.ST_KEY=0;
  setTransformBusy(false);
  setSpeedUI(1, false);
  setKeyUI(0, false);
}
NH.cancelSoundTouch = cancelSoundTouch;
function resetSpeedTo1(){
  cancelSoundTouch();
  setSpeedUI(1, false);
  const resetRate=document.getElementById('rate');
  if(resetRate) resetRate.value='1';
  NH.au.playbackRate=1;
  setKeyUI(0, false);
}
async function switchStAt(sourcePos, wasPlaying, token, uid, target){
  if(token!==stToken || !target || String(target.uid)!==String(uid)) return false;
  NH.commitAudio(target);
  const t = Math.max(0, NH.audioTime(sourcePos));
  if(!await NH.seekPlayback(t)) return false;
  if(token!==stToken || String(NH.PLAYING_UID)!==String(uid)) return false;
  if(wasPlaying) await NH.au.play().catch(()=>{});
  return true;
}

function snapshotST(){
  return {on:NH.ST_ON, url:NH.ST_URL, uid:NH.ST_UID, speed:NH.ST_SPEED,
          key:NH.ST_KEY || 0};
}

async function restoreST(snap, target, sourcePos, wasPlaying, token){
  if(token!==stToken) return;
  NH.ST_ON=snap.on; NH.ST_URL=snap.url; NH.ST_UID=snap.uid; NH.ST_SPEED=snap.speed;
  NH.ST_KEY=snap.key || 0;
  setKeyUI(NH.ST_KEY, false);
  const shown=snap.on ? (snap.speed||1) : 1;
  setSpeedUI(shown, false);
  if(!target) return;
  NH.commitAudio(target);
  const t=snap.on ? sourcePos/(snap.speed||1) : sourcePos;
  if(!await NH.seekPlayback(t)) throw new Error('恢复播放位置失败');
  if(wasPlaying) await NH.au.play().catch(()=>{});
}

async function forceOriginal(target, sourcePos, token){
  if(token!==stToken) return;
  NH.ST_ON=false; NH.ST_URL=null; NH.ST_UID=null; NH.ST_SPEED=1;
  NH.ST_KEY=0;
  setKeyUI(0, false);
  setSpeedUI(1, false);
  if(!target) return;
  NH.commitAudio(target);
  await NH.seekPlayback(Math.max(0, sourcePos));
}

function normalizeSpeed(speed){
  speed = Math.max(0.5, Math.min(1.25, +speed || 1));
  return SPEED_VALUES.reduce((best, v) =>
    Math.abs(v - speed) < Math.abs(best - speed) ? v : best, SPEED_VALUES[0]);
}
function currentTransformSpeed(){
  const el=document.getElementById('rate');
  return normalizeSpeed(+(el && el.value) || 1);
}
function keyLabel(key){
  return key ? (key > 0 ? '+' + key : String(key)) : '原调';
}
function speedLabel(speed){
  const text=(+speed || 1).toFixed(2).replace(/0$/, '');
  return text + '×';
}
function setSpeedUI(speed, busy){
  speed = normalizeSpeed(speed);
  const rate=document.getElementById('rate');
  if(rate) rate.value=speed.toFixed(2);
  const rv=document.getElementById('rv');
  if(rv) rv.textContent=speedLabel(speed);
  const sp=document.getElementById('speedpick');
  if(sp) sp.textContent=speedLabel(speed);
  if(sp) sp.disabled=!!busy;
}
function setKeyUI(key, busy){
  key = Math.max(KEY_MIN, Math.min(KEY_MAX, parseInt(key, 10) || 0));
  NH.ST_KEY = key;
  const kp=document.getElementById('keypick');
  if(kp) kp.textContent=keyLabel(key);
  if(kp) kp.disabled=!!busy;
}
function setTransformBusy(busy){
  if(busy) closeValueMenu();
  const rate=document.getElementById('rate');
  if(rate) rate.disabled=!!busy;
  setKeyUI(NH.ST_KEY || 0, !!busy);
  const sp=document.getElementById('speedpick');
  if(sp){ sp.textContent=speedLabel(currentTransformSpeed()); sp.disabled=!!busy; }
}

let valueMenu = null;
function closeValueMenu(){
  if(valueMenu){ valueMenu.remove(); valueMenu=null; }
}
function openValueMenu(anchor, values, current, pick, label){
  closeValueMenu();
  if(!anchor || anchor.disabled) return;
  const menu=document.createElement('div');
  menu.className='valmenu';
  let selected=null;
  values.forEach(v=>{
    const b=document.createElement('button');
    b.type='button';
    b.textContent=label(v);
    if(String(v)===String(current)){ b.classList.add('on'); selected=b; }
    b.onclick=ev=>{
      ev.stopPropagation();
      closeValueMenu();
      pick(v);
    };
    menu.appendChild(b);
  });
  document.body.appendChild(menu);
  valueMenu=menu;
  const r=anchor.getBoundingClientRect();
  const w=r.width;
  const h=menu.offsetHeight || 220;
  menu.style.width=Math.round(w)+'px';
  let top=r.top-h-6;
  if(top<8) top=Math.min(innerHeight-h-8, r.bottom+6);
  let left=Math.min(r.left, innerWidth-w-8);
  left=Math.max(8, left);
  menu.style.left=left+'px';
  menu.style.top=Math.max(8, top)+'px';
  // 当前项垂直居中；列表顶部/底部自然贴边。
  if(selected){
    const offset=selected.offsetTop - (menu.clientHeight - selected.offsetHeight) / 2;
    menu.scrollTop=Math.max(0, Math.min(menu.scrollHeight - menu.clientHeight, offset));
  }
}
function openKeyPicker(){
  if(stBusy) return;
  openValueMenu(document.getElementById('keypick'),
    [6,5,4,3,2,1,0,-1,-2,-3,-4,-5,-6], NH.ST_KEY || 0,
    v=>applyKey(v), keyLabel);
}
function openSpeedPicker(){
  if(stBusy) return;
  openValueMenu(document.getElementById('speedpick'),
    SPEED_VALUES, currentTransformSpeed(),
    v=>{ setSpeedUI(v, false); applySpeed(v); }, v=>speedLabel(v));
}
document.addEventListener('click', ev=>{
  if(!valueMenu) return;
  const a=document.getElementById('keypick'), b=document.getElementById('speedpick');
  if((a && a.contains(ev.target)) || (b && b.contains(ev.target))) return;
  if(!valueMenu.contains(ev.target)) closeValueMenu();
});
document.addEventListener('keydown', ev=>{
  if(ev.key==='Escape') closeValueMenu();
});

async function applyTransform(speed, key){
  speed = normalizeSpeed(speed);
  key = Math.max(KEY_MIN, Math.min(KEY_MAX, parseInt(key, 10) || 0));
  if(stBusy){ stWantSpeed=speed; stWantKey=key; return; }
  if(Math.abs(speed - 1) < 0.001 && key === 0){
    NH.ST_KEY=0;
    setKeyUI(0, false);
    setSpeedUI(1, false);
    if(!NH.ST_ON){ NH.au.playbackRate = 1; return; }
    const target=speedTarget();
    if(!target) return;
    const token=++stToken;
    const uid=target.uid;
    const pos=stSourcePos();
    const wasPlaying=!NH.au.paused;
    const snap=snapshotST();
    NH.ST_ON=false; NH.ST_URL=null; NH.ST_UID=null; NH.ST_SPEED=1;
    stBusy=true;
    setTransformBusy(true);
    try{
      if(!await switchStAt(pos, wasPlaying, token, uid, target))
        throw new Error('切换播放位置失败');
      if(token===stToken) NH.flash('已回到原速原调');
    }catch(e){
      if(token===stToken){
        let restored=false;
        try{
          await restoreST(snap, target, pos, wasPlaying, token);
          restored=true;
        }catch(e2){
          NH.reportClientError?.('soundtouch_restore', e2.message, '',
            {uid:target.uid, speed:snap.speed, key:snap.key});
          try{ await forceOriginal(target, pos, token); }catch(e3){}
        }
        if(restored){
          NH.reportClientError?.('soundtouch_switch', e.message, '',
            {uid:target.uid, speed:snap.speed, key:snap.key});
        }else{
          NH.done('SoundTouch 恢复失败，已回到 1.00×');
        }
      }
    }finally{
      if(token===stToken){
        stBusy=false;
        setTransformBusy(false);
        if(stWantSpeed!==null || stWantKey!==null){
          const nextS=stWantSpeed == null ? speed : stWantSpeed;
          const nextK=stWantKey == null ? key : stWantKey;
          stWantSpeed=stWantKey=null;
          applyTransform(nextS, nextK);
        }
      }
    }
    return;
  }
  const target=speedTarget();
  if(!target){ setKeyUI(key, false); setSpeedUI(speed, false); return; }
  if(NH.ST_ON && Math.abs(speed - NH.ST_SPEED) < 0.001 && key === (NH.ST_KEY || 0)){
    setKeyUI(key, false);
    return;
  }
  const snap=snapshotST();
  const token=++stToken;
  const uid=target.uid;
  const pos=stSourcePos();
  const wasPlaying=!NH.au.paused;
  stBusy=true;
  setTransformBusy(true);
  const label=key ? `${speed.toFixed(2)}× ${keyLabel(key)}` : `${speed.toFixed(2)}×`;
  NH.busy(`SoundTouch ${label} 生成中…`);
  try{
    const r=await NH.api('/api/soundtouch',{uid, speed, key});
    if(token!==stToken || !target) return;
    if(NH.PLAYING_UID!==null && NH.PLAYING_UID!==undefined
       && String(NH.PLAYING_UID)!==String(uid)) return;
    if(r.ok===false) throw new Error(r.error||'生成失败');
    NH.ST_ON=true; NH.ST_URL=r.url; NH.ST_UID=uid;
    NH.ST_SPEED=speed; NH.ST_KEY=key;
    setKeyUI(key, false);
    setSpeedUI(speed, false);
    try{
      if(!await switchStAt(pos, wasPlaying, token, uid, target))
        throw new Error('切换播放位置失败');
      if(token===stToken) NH.flash(`SoundTouch ${label}：已切换`);
    }catch(err){
      let restored=false;
      let forced=false;
      if(token===stToken){
        try{
          await restoreST(snap, target, pos, wasPlaying, token);
          restored=true;
        }catch(e2){
          NH.reportClientError?.('soundtouch_restore', e2.message, '',
            {uid:target.uid, speed:snap.speed, key:snap.key});
          try{ await forceOriginal(target, pos, token); }catch(e3){} finally{ forced=true; }
        }
      }
      throw {error:err, restored, forced};
    }
  }catch(e){
    if(token===stToken){
      const switched=e && e.error;
      const restored=!!(e && e.restored);
      const forced=!!(e && e.forced);
      const shown=snap.on ? (snap.speed||1) : 1;
      if(!switched){
        setSpeedUI(shown, false);
        setKeyUI(snap.key || 0, false);
        const why = e.code==='invalid_key' ? '音程参数无效'
          : e.code==='invalid_speed' ? '速度参数无效'
          : e.code==='song_missing' ? '歌曲已不可用'
          : e.code==='soundtouch_failed' ? '生成器不可用'
          : (e.message||'未知错误');
        NH.done('SoundTouch 生成失败：'+why);
      }else{
        if(!restored && !forced){
          setSpeedUI(shown, false);
          setKeyUI(snap.key || 0, false);
        }
        if(restored){
          NH.reportClientError?.('soundtouch_switch', e.error.message, '',
            {uid:target.uid, speed:snap.speed, key:snap.key});
        }else{
          NH.done('SoundTouch 恢复失败，已回到 1.00×');
        }
      }
    }
  }finally{
    if(token===stToken){
      stBusy=false;
      setTransformBusy(false);
      if(stWantSpeed!==null || stWantKey!==null){
        const nextS=stWantSpeed == null ? speed : stWantSpeed;
        const nextK=stWantKey == null ? key : stWantKey;
        stWantSpeed=stWantKey=null;
        applyTransform(nextS, nextK);
      }
    }
  }
}

async function applySpeed(speed){
  return applyTransform(speed, NH.ST_KEY || 0);
}
async function applyKey(key){
  return applyTransform(currentTransformSpeed(), key);
}

document.getElementById('rate').oninput=e=>{
  const v=+e.target.value;
  const sp=document.getElementById('speedpick');
  if(sp) sp.textContent=speedLabel(v);
  const rv=document.getElementById('rv');
  if(rv) rv.textContent=speedLabel(v);
  if(!NH.ST_ON) NH.au.playbackRate=1;
};
document.getElementById('rate').onchange=e=>applySpeed(+e.target.value);
const keyPick=document.getElementById('keypick');
if(keyPick) keyPick.onclick=openKeyPicker;
const speedPick=document.getElementById('speedpick');
if(speedPick) speedPick.onclick=openSpeedPicker;
setKeyUI(0, false);
setSpeedUI(1, false);
async function stepPlaying(dir){
  if(NH.PLAYING_UID===null) return;
  if(!NH.isSelfPlaying()){
    const ok=await NH.load(NH.PLAYING_UID, false);   // 页面跳到 A，不打断 A
    if(!ok) return;
  }
  const n=nextIdx(dir); if(n!==null) seekIdx(n);
}
document.getElementById('prev').onclick=()=>stepPlaying(-1);
document.getElementById('next').onclick=()=>stepPlaying(1);

function songOrderUids(){
  const cur=NH.PLAYING_UID!==null && NH.PLAYING_UID!==undefined
    ? String(NH.PLAYING_UID) : (NH.S ? String(NH.S.uid) : '');
  const groups=NH.PLS||[];
  const has=g=>(g.items||[]).some(x=>String(x.uid)===cur);
  // 正在播放的歌优先；没有播放时用当前查看的歌。
  let g=groups.find(x=>x.id===NH.SEL_LIST && has(x)) || groups.find(has);
  const items=g ? (g.items||[]) : (NH.LIB||[]);
  return [...new Set(items.map(x=>String(x.uid)).filter(Boolean))];
}
function stepSong(dir){
  const uids=songOrderUids();
  if(!uids.length) return;
  if(NH.playMode === 'shuffle'){
    const target = takeShuffleUid(uids, currentPlayUid());
    if(!target) return;
    const follow = NH.S && String(NH.S.uid) === String(NH.PLAYING_UID);
    if(follow) NH.load(target, true);
    else playTarget(target);
    return;
  }
  const cur=NH.PLAYING_UID!==null && NH.PLAYING_UID!==undefined
    ? String(NH.PLAYING_UID) : (NH.S ? String(NH.S.uid) : '');
  let at=uids.indexOf(cur);
  if(at<0) at=dir>0?-1:0;
  const target=uids[(at+dir+uids.length)%uids.length];
  if(!target) return;
  const follow = NH.S && String(NH.S.uid) === String(NH.PLAYING_UID);
  if(follow) NH.load(target, true);
  else playTarget(target);
}
document.getElementById('prevSong').onclick=()=>stepSong(-1);
document.getElementById('nextSong').onclick=()=>stepSong(1);
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
  if(!d.candidates || !d.candidates.length){
    const msg = d.status==='network_error' ? '网络请求失败，请稍后重试'
      : d.status==='no_lyrics' ? '找到了候选，但没有可用歌词'
      : '没找到候选，可以试试手动导入 lrc';
    NH.done(msg); NH.lock(null,false); return;
  }
  NH.flash(`找到 ${d.candidates.length} 个候选`); NH.lock(null,false);
  const box=document.createElement('div'); box.className='menu'; box.style.maxWidth='520px';
  box.innerHTML='<div style="font-size:12px;color:var(--muted);padding:4px 8px">选一个（分数越高越可能是同一版）· 候选来自网络，不读本地缓存</div>';
  d.candidates.forEach(c=>{
    const b=document.createElement('button');
    const mm=Math.floor(c.duration/60), ss=String(Math.round(c.duration%60)).padStart(2,'0');
    const delta=(c.delta===null||c.delta===undefined)?'' : (c.delta>=0?'+':'')+c.delta+'s';
    b.innerHTML=`${NH.esc(c.name)} · ${NH.esc(c.artist)} · ${mm}:${ss} ${NH.esc(delta)} · ${NH.esc(c.score)}`;
    if(!c.id){                       // 没有 id 的条目不可切换
      b.onclick=ev=>{ev.stopPropagation(); NH.flash('当前用的就是这条');};
      b.style.opacity='.6';
    }else b.onclick=async ev=>{ev.stopPropagation();
      if(NH.S!==song || NH.VIEW_MODE==='lrc'){ box.remove(); return; }
      box.remove();
      NH.busy('换歌词中…');
      try{
        const d=await NH.api('/api/pick',{action:'pick', uid:song.uid, id:c.id,
          version:NH.LRC_VERSION || (NH.S && NH.S.version)});
        if(!d.ok){ NH.done(d.error||'换歌词失败'); return; }
        if(NH.S!==song || NH.VIEW_MODE==='lrc') return;
        NH.NO_MATCH.delete(String(d.uid || song.uid));
        await NH.load(d.uid || song.uid);        // 重新拉这一首（已换新歌词）
        NH.loadLib();
        NH.flash(`已换成 ${c.name}（${d.lines} 行歌词）`);
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

// ── 播放模式：列表循环 / 单曲循环 / 随机播放 ──────────
const PLAY_MODE_ORDER = ['list', 'one', 'shuffle'];
const PLAY_MODE_LABEL = {list: '列表循环', one: '单曲循环', shuffle: '随机播放'};
const initialPlayMode = (CFG.player && CFG.player.ui && CFG.player.ui.play_mode);
NH.playMode = PLAY_MODE_ORDER.includes(initialPlayMode) ? initialPlayMode : 'list';
NH.PLAY_ITEM = null;
NH.shufflePool = [];
NH.shuffleListKey = '';
const songLoopBtn = document.getElementById('songloop');
function syncPlayMode(){
  if(!songLoopBtn) return;
  songLoopBtn.textContent = PLAY_MODE_LABEL[NH.playMode] || PLAY_MODE_LABEL.list;
  songLoopBtn.classList.add('on');
}
let PLAY_MODE_SEQ = 0;
function applyPlayMode(mode){
  NH.playMode = mode;
  if(mode === 'shuffle'){
    resetShufflePool(songOrderUids(), currentPlayUid());
  }else{
    NH.shufflePool = []; NH.shuffleListKey = '';
  }
  syncPlayMode();
}

function setPlayMode(mode, persist){
  if(!PLAY_MODE_ORDER.includes(mode)) mode = 'list';
  const prev = NH.playMode;
  applyPlayMode(mode);
  if(persist && NH.api){
    const seq = ++PLAY_MODE_SEQ;
    NH.api('/api/play_mode', {mode}).then(r=>{
      if(seq !== PLAY_MODE_SEQ) return;
      if(r && r.ok === false){
        applyPlayMode(prev);
        NH.done(r.error || '播放模式保存失败');
      }else if(r && r.warning) NH.done(r.warning);
    }).catch(e=>{
      if(seq !== PLAY_MODE_SEQ) return;
      applyPlayMode(prev);
      NH.done('播放模式保存失败：' + e.message);
    });
  }
}
function cyclePlayMode(){
  const at = PLAY_MODE_ORDER.indexOf(NH.playMode);
  setPlayMode(PLAY_MODE_ORDER[(at + 1) % PLAY_MODE_ORDER.length], true);
}
if(songLoopBtn) songLoopBtn.onclick = cyclePlayMode;
syncPlayMode();

function currentPlayUid(){
  return NH.PLAYING_UID !== null && NH.PLAYING_UID !== undefined
    ? String(NH.PLAYING_UID) : (NH.S ? String(NH.S.uid) : '');
}

function resetShufflePool(uids, current){
  const uniq = [...new Set((uids || []).map(String).filter(Boolean))];
  NH.shuffleListKey = uniq.slice().sort().join('\n');
  NH.shufflePool = uniq.filter(u => u !== String(current || ''))
    .sort(() => Math.random() - 0.5);
}

function markShufflePlayed(uid){
  if(NH.playMode !== 'shuffle' || !uid) return;
  const u = String(uid);
  NH.shufflePool = (NH.shufflePool || []).filter(x => String(x) !== u);
}

function takeShuffleUid(uids, current){
  const list = [...new Set((uids || []).map(String).filter(Boolean))];
  const key = list.slice().sort().join('\n');
  if(key !== NH.shuffleListKey){
    resetShufflePool(list, current);
  } else {
    NH.shufflePool = (NH.shufflePool || [])
      .filter(u => list.includes(String(u)) && String(u) !== String(current || ''));
  }
  if(!NH.shufflePool.length){
    resetShufflePool(list, current);
  }
  return NH.shufflePool.length ? NH.shufflePool.shift() : (list[0] || null);
}

NH.au.addEventListener('ended', () => {
  const endedUid = NH.PLAYING_UID;
  if(endedUid === null || endedUid === undefined) return;
  // 等引擎的 ended/pause 流程走完再起新 source，避免把 watch 循环覆盖。
  setTimeout(async () => {
    if(String(NH.PLAYING_UID) !== String(endedUid)) return;
    if(NH.playMode === 'one'){
      NH.au.currentTime = 0;
      NH.au.play().catch(()=>{});
      return;
    }
    await stepSong(1);
  }, 0);
});


NH.mediaPrev = () => stepSong(-1);
NH.mediaNext = () => stepSong(1);
NH.mediaToggle = () => togglePlayPause();
Object.assign(NH, {markPlaying, applySpeed, applyKey, setKeyUI, setSpeedUI,
  SPEED_VALUES, normalizeSpeed, speedLabel,
  openKeyPicker, openSpeedPicker, closeValueMenu, commitAudio, playTarget, syncBackPlaying, findSongItem, syncPlayControls, stepSong, togglePlayPause, viewLines, lineT, isMetaLine, idxAt, navItems, onceEvent, audioReady, seekPrecise, seekPlayback, seekIdx, selectLine, playLine, nextIdx, highlight, seek, fmtTime, paintTransport, paintTicks, seekToClientX, syncPlayBtn, stepPlaying, setPlayMode, cyclePlayMode, syncPlayMode, takeShuffleUid, resetShufflePool, markShufflePlayed, currentPlayUid});
})();
