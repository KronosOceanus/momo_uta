/* 命名空间模块：应用内快捷键分发（全局热键在 Python 侧） */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});

function helpEl(){
  let el=document.getElementById('shortcuthelp');
  if(el) return el;
  el=document.createElement('div'); el.id='shortcuthelp'; el.hidden=true;
  el.innerHTML=`<div class="sk-box" role="dialog" aria-label="快捷键">
    <div class="sk-title">快捷键 <span>Esc 关闭</span></div>
    <div class="sk-grid">
      <b>播放</b>
      <div><kbd>Space</kbd> 播放 / 暂停</div>
      <div><kbd>←</kbd> <kbd>→</kbd> 上一句 / 下一句</div>
      <div><kbd>Alt</kbd>+<kbd>←</kbd> / <kbd>Alt</kbd>+<kbd>→</kbd> 上一首 / 下一首</div>
      <div><kbd>Shift</kbd>+<kbd>←</kbd> / <kbd>Shift</kbd>+<kbd>→</kbd> 后退 / 前进 10 秒</div>
      <div><kbd>M</kbd> 静音　<kbd>[</kbd> / <kbd>]</kbd> 速度</div>
      <div><kbd>L</kbd> 单句循环　<kbd>Shift</kbd>+<kbd>L</kbd> 单曲循环</div>
      <b>LRC 编辑</b>
      <div><kbd>Cmd</kbd>+<kbd>S</kbd> 保存　<kbd>T</kbd> 翻译列</div>
      <div><kbd>Enter</kbd> 加行　<kbd>Delete</kbd> 删行</div>
      <div><kbd>Cmd</kbd>+<kbd>A</kbd> 全选　<kbd>Cmd</kbd>+<kbd>Z</kbd> 撤销 / 重做</div>
      <b>后台</b>
      <div><kbd>⌃</kbd>+<kbd>⌥</kbd>+<kbd>←</kbd> / <kbd>→</kbd> 上一首 / 下一首</div>
      <div><kbd>⌃</kbd>+<kbd>⌥</kbd>+<kbd>P</kbd> 播放 / 暂停</div>
    </div>
  </div>`;
  el.addEventListener('click', e=>{ if(e.target===el) closeHelp(); });
  document.body.appendChild(el);
  return el;
}
function closeHelp(){ const el=document.getElementById('shortcuthelp'); if(el) el.hidden=true; }
function toggleHelp(){ const el=helpEl(); el.hidden=!el.hidden; }

function isTyping(t){
  if(!t) return false;
  const tag=(t.tagName||'').toUpperCase();
  return tag==='INPUT' || tag==='TEXTAREA' || tag==='SELECT' || t.isContentEditable;
}
function isButton(t){
  return !!t && (t.tagName||'').toUpperCase()==='BUTTON';
}
function speed(delta){
  const el=document.getElementById('rate'); if(!el) return;
  const min=parseFloat(el.min)||0.5, max=parseFloat(el.max)||1.25;
  const step=parseFloat(el.step)||0.05;
  el.value=Math.max(min, Math.min(max, (+el.value||1)+delta*step));
  el.dispatchEvent(new Event('input',{bubbles:true}));
}
function seek(delta){
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  const dur=isFinite(NH.au.duration)?NH.au.duration:0;
  NH.seekPrecise(Math.max(0, Math.min(dur||0, (NH.au.currentTime||0)+delta)));
}

document.addEventListener('keydown', e=>{
  if(e.isComposing || e.keyCode===229 || e.defaultPrevented) return;
  const t=e.target || {};
  if(isTyping(t) || isButton(t)) return;
  if(document.querySelector('.dialog-backdrop')) return;

  if(e.key==='Escape'){ closeHelp(); return; }
  if(e.key==='?'){ e.preventDefault(); toggleHelp(); return; }
  if(e.metaKey || e.ctrlKey){
    const k=(e.key||'').toLowerCase();
    if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED){
      if(k==='s'){ e.preventDefault(); NH.saveLrc(false,true); return; }
      if(k==='a'){ e.preventDefault(); NH.selectAll(); return; }
      if(k==='z'){ e.preventDefault(); e.shiftKey?NH.redo():NH.undo(); return; }
    }
    return;
  }
  if(e.altKey){
    if(e.key==='ArrowLeft'){ e.preventDefault(); NH.stepSong(-1); }
    else if(e.key==='ArrowRight'){ e.preventDefault(); NH.stepSong(1); }
    return;
  }
  if(e.shiftKey && (e.key==='ArrowLeft' || e.key==='ArrowRight')){
    e.preventDefault(); seek(e.key==='ArrowLeft'?-10:10); return;
  }
  if(e.key===' ' || e.code==='Space'){
    e.preventDefault(); NH.togglePlayPause(); return;
  }
  if(e.key==='ArrowLeft'){ e.preventDefault(); document.getElementById('prev').click(); return; }
  if(e.key==='ArrowRight'){ e.preventDefault(); document.getElementById('next').click(); return; }
  if(e.key==='m' || e.key==='M'){ e.preventDefault(); NH.au.muted=!NH.au.muted; NH.paintTransport(); return; }
  if(e.key==='['){ e.preventDefault(); speed(-1); return; }
  if(e.key===']'){ e.preventDefault(); speed(1); return; }
  if(e.key==='l' || e.key==='L'){
    e.preventDefault();
    if(e.shiftKey) document.getElementById('songloop').click();
    else document.getElementById('loop').click();
    return;
  }
  if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED){
    if(e.key==='Enter'){ e.preventDefault(); NH.addRow(); return; }
    if(e.key==='Delete' || e.key==='Backspace'){ e.preventDefault(); NH.delRows(); return; }
    if(e.key==='t' || e.key==='T'){ e.preventDefault(); document.getElementById('lrctrans').click(); return; }
  }
});

NH.toggleShortcutHelp = toggleHelp;
})();
