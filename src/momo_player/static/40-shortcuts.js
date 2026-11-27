/* 命名空间模块：应用内快捷键分发（全局热键在 Python 侧） */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});

function helpEl(){
  let el=document.getElementById('shortcuthelp');
  if(el) return el;
  el=document.createElement('div'); el.id='shortcuthelp'; el.hidden=true;
  const k = (...keys) => keys.map(x => `<kbd>${x}</kbd>`).join('');
  const plus = '<span class="sk-plus">+</span>';
  const combo = (...keys) => keys.map(x => `<kbd>${x}</kbd>`).join(plus);
  const sep = ' <span class="sk-sep">/</span> ';
  const sections = [
    ['播放', [
      [k('Space'), '播放 / 暂停'],
      [combo('←') + sep + combo('→'), '上一句 / 下一句'],
      [combo('Alt','←') + sep + combo('Alt','→'), '上一首 / 下一首'],
      [combo('Shift','←') + sep + combo('Shift','→'), '后退 / 前进 10 秒'],
      [k('B'), '回到正在播放歌曲'],
      [k('M'), '静音'],
      [combo('[') + sep + combo(']'), '速度 − / +'],
      [k('-') + sep + k('='), '降 / 升 key'],
      [k('L'), '单句循环'],
      [combo('Shift','L'), '播放模式'],
    ]],
    ['LRC 编辑', [
      [combo('Cmd','S'), '保存歌词（普通页 / 编辑页）'],
      [k('T'), '翻译列开关'],
      [k('Enter'), '新增一行'],
      [k('Delete'), '删除选中行'],
      [combo('Cmd','A'), '全选行'],
      [combo('Cmd','Z') + sep + combo('Shift','Cmd','Z'), '撤销 / 重做'],
    ]],
    ['全局 / 后台', [
      [combo('⌃','⌥','←') + sep + combo('⌃','⌥','→'), '上一首 / 下一首'],
      [combo('⌃','⌥','P'), '播放 / 暂停'],
    ]],
    ['界面', [
      [k('?'), '打开快捷键帮助'],
      [k('Esc'), '关闭帮助'],
    ]],
  ];
  const body = sections.map(([title, rows]) => `
    <section class="sk-section">
      <h4>${title}</h4>
      ${rows.map(([keys, desc]) => `<div class="sk-row"><div class="sk-key">${keys}</div><div class="sk-desc">${desc}</div></div>`).join('')}
    </section>`).join('');
  el.innerHTML=`<div class="sk-box" role="dialog" aria-label="快捷键">
    <div class="sk-title">快捷键 <span>Esc 关闭</span></div>
    ${body}
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
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  const el=document.getElementById('rate'); if(!el) return;
  const vals=(NH.SPEED_VALUES || [1.25,1.2,1.1,1.0,0.9,0.8,0.7,0.6,0.5]);
  const cur=+el.value||1;
  let at=0;
  for(let i=1;i<vals.length;i++)
    if(Math.abs(vals[i]-cur)<Math.abs(vals[at]-cur)) at=i;
  at += delta < 0 ? 1 : -1;                 // vals 从高到低
  at=Math.max(0, Math.min(vals.length-1, at));
  el.value=vals[at];
  el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}));
}
function seek(delta){
  if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
  const dur=isFinite(NH.au.duration)?NH.au.duration:0;
  NH.seekPrecise(Math.max(0, Math.min(dur||0, (NH.au.currentTime||0)+delta)));
}

document.addEventListener('keydown', e=>{
  if(e.isComposing || e.keyCode===229 || e.defaultPrevented) return;
  const t=e.target || {};
  if(isTyping(t)) return;
  if(document.querySelector('.dialog-backdrop')) return;

  if(e.key==='Escape'){ closeHelp(); return; }
  if(e.key==='?' || ((e.key==='/' || e.code==='Slash' || e.keyCode===191) && e.shiftKey)){
    e.preventDefault(); toggleHelp(); return;
  }
  // 组合键先于 isButton：点过播放按钮后焦点仍在按钮上时，Cmd+S 也要能用。
  if(e.metaKey || e.ctrlKey){
    const k=(e.key||'').toLowerCase();
    if(k==='s'){
      e.preventDefault();
      if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED)
        NH.saveLrc(false,true);
      else if(NH.VIEW_MODE==='normal' || NH.VIEW_MODE==='kana')
        NH.persistCurrentLyrics?.();
      return;
    }
    if(NH.VIEW_MODE==='lrc' && !NH.LRC_LOCKED){
      if(k==='a'){ e.preventDefault(); NH.selectAll(); return; }
      if(k==='z'){ e.preventDefault(); e.shiftKey?NH.redo():NH.undo(); return; }
    }
    return;
  }
  const passthrough = e.key === '-' || e.key === '=' || e.key === '+'
    || e.key === '[' || e.key === ']'
    || e.code === 'Minus' || e.code === 'Equal'
    || e.code === 'BracketLeft' || e.code === 'BracketRight';
  if(isButton(t) && !passthrough) return;
  if(e.key==='b' || e.key==='B'){
    const back=document.getElementById('backplaying');
    if(back && !back.hidden){ e.preventDefault(); back.click(); }
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
  const keyDown = (e.key === '-' || e.code === 'Minus') && !e.shiftKey;
  const keyUp = e.key === '=' || e.key === '+' || e.code === 'Equal';
  if(keyDown || keyUp){
    e.preventDefault();
    if(e.repeat) return;
    if(NH.PLAYING_UID===null || NH.PLAYING_UID===undefined) return;
    NH.applyKey((NH.ST_KEY || 0) + (keyUp ? 1 : -1));
    return;
  }
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
