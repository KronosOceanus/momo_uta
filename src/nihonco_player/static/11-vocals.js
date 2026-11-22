/* 命名空间模块：人声任务状态 / 任务列表 / 取消 */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
const JOB=(NH.CFG&&NH.CFG.jobs)||{};
const VC=(NH.CFG&&NH.CFG.vocals)||{};
NH.VSTAT = null; NH.VSTAT_IDX = null;
NH.VJOBS = new Map();                 // id -> {id, uid, state}
function vActive(j){ return !!j && (j.state==='queued' || j.state==='running' || j.state==='canceling'); }
function vJobs(){ return [...NH.VJOBS.values()].filter(vActive); }
function vCurrentJob(){
  if(!NH.S) return null;
  return vJobs().find(j=>String(j.uid)===String(NH.S.uid)) || null;
}
function vJobTitle(j){
  if(NH.S && String(NH.S.uid)===String(j.uid)) return NH.S.title || j.uid;
  const it=(NH.LIB||[]).find(x=>String(x.uid)===String(j.uid));
  return it ? (it.title || it.orig || j.uid) : j.uid;
}
function vStage(j){
  return (j && (j.stage || j.state)) || '';
}
function vStateText(s){
  return s==='running'?'执行中':s==='queued'?'排队':s==='canceling'?'正在取消…':'';
}
function renderVTasks(){
  const box=document.getElementById('vtasks'), list=document.getElementById('vtasklist'),
        all=document.getElementById('vcancelall');
  if(!box || !list || !all) return;
  const jobs=vJobs().slice().sort((a,b)=>{
    const rank=x=>x.state==='running'?0:x.state==='canceling'?1:2;
    return rank(a)-rank(b) || (a.id>b.id?1:-1);
  });
  if(!jobs.length){ closeVTasks(true); return; }
  const cur=vCurrentJob();
  // 只更新内容；显示/隐藏由 open/close 决定，避免轮询把列表强行打开。
  const sig=jobs.map(j=>`${j.id}:${j.state}:${vStage(j)}:${j.uid}:${vJobTitle(j)}`).join('|')+
            '|cur:'+(cur?cur.id:'');
  if(sig===NH.VLIST_SIG) return;
  NH.VLIST_SIG=sig;
  list.innerHTML='';
  jobs.forEach(j=>{
    const row=document.createElement('div'); row.className='vrow';
    const nm=document.createElement('span'); nm.className='vnm';
    nm.textContent=(cur && cur.id===j.id ? '当前 · ' : '') + vJobTitle(j);
    const stage=vStage(j);
    const st=document.createElement('span'); st.className='vst '+(stage==='running'?'run':stage==='queued'?'que':'');
    st.textContent=vStateText(stage);
    const b=document.createElement('button'); b.dataset.vcancel=j.id;
    b.textContent=stage==='canceling'?'取消中':'取消'; b.disabled=stage==='canceling';
    row.append(nm,st,b); list.appendChild(row);
  });
  const showAll=jobs.length>1 || !cur;
  all.hidden=!showAll;
  const pending=jobs.some(j=>j.state==='queued' || j.state==='running');
  all.disabled=!pending;
  all.textContent=pending?`取消全部人声 (${jobs.length})`:'正在取消…';
}
function paintVCancel(){
  const bg=document.getElementById('vbackground');
  if(!bg) return;
  const cur=vCurrentJob(), jobs=vJobs();
  const others=jobs.filter(j=>!cur || j.id!==cur.id);
  if(others.length){
    bg.hidden=false;
    bg.textContent=`后台人声 ${others.length}`;
  }else bg.hidden=true;
  renderVTasks();
}
function openVTasks(pin){
  if(!vJobs().length) return;
  clearTimeout(NH.VLIST_T);
  if(pin) NH.VLIST_PIN=true;
  renderVTasks();
  const box=document.getElementById('vtasks'); if(box) box.hidden=false;
}
function closeVTasks(force){
  if(!force && NH.VLIST_PIN) return;
  NH.VLIST_PIN=false;
  clearTimeout(NH.VLIST_T);
  const box=document.getElementById('vtasks'); if(box) box.hidden=true;
}
function scheduleCloseVTasks(){
  if(NH.VLIST_PIN) return;
  clearTimeout(NH.VLIST_T);
  NH.VLIST_T=setTimeout(()=>{ if(!NH.VLIST_PIN) closeVTasks(true); },180);
}
NH.VLIST_PIN=false; NH.VLIST_T=null; NH.VLIST_SIG=null;

function paintVStatus(){
  const el=document.getElementById('vchip');
  if(el){
    if(!NH.VSTAT || NH.VSTAT.state==='none') el.hidden=true;
    else{
      el.hidden=false;
      if(NH.VSTAT.state==='done'){
        el.textContent = NH.VSTAT.has_vocals ? '有人声' : '纯音乐';
        el.classList.toggle('vdone', true);
        el.classList.toggle('vinst', !NH.VSTAT.has_vocals);
      }else if(NH.VSTAT.state==='failed'){
        el.textContent='人声分离失败';
      }else if(NH.VSTAT.state==='canceled'){
        el.textContent='已取消';
      }else if(NH.VSTAT.state==='canceling'){
        el.textContent='正在取消…';
      }else if(NH.VSTAT.state==='queued'){
        el.textContent='人声分离：排队';
      }else{
        el.textContent='人声分离中…';
      }
    }
  }
  paintVCancel();
}
async function startVocals(uid){
  if(VC.auto_start===false) return;
  const st=NH.VSTAT;
  if(NH.VSTAT_IDX===String(uid) && st && (st.state==='queued' || st.state==='running' || st.state==='done')) return;
  NH.VSTAT_IDX=String(uid);
  NH.VSTAT={state:'running'};
  paintVStatus();
  let job=null;
  try{
    job=await NH.api('/api/jobs',{kind:'vocals', uid});
    const rec={id:job.id, uid:String(uid), state:job.state||'queued',
               stage:job.stage||job.state||'queued'};
    NH.VJOBS.set(rec.id, rec);
    if(NH.S && String(NH.S.uid)===String(uid)){ NH.VSTAT={state:vStage(rec)}; paintVStatus(); }
    const done=await NH.waitJob(job.id, (j)=>{
      rec.state=j.state;
      rec.stage=j.stage || j.state;
      if(NH.S && String(NH.S.uid)===String(uid)){
        NH.VSTAT = (j.state==='done') ? (j.result || {state:'done'})
          : (j.state==='canceled') ? {state:'canceled', error:j.error||'已取消'}
          : (j.state==='failed') ? {state:'failed', error:j.error||'人声分离失败'}
          : {state:vStage(j)};
        paintVStatus();
      }
      paintVCancel();
    });
    NH.VJOBS.delete(job.id);
    if(!NH.S || String(NH.S.uid)!==String(uid)){ paintVCancel(); return; }
    if(done.state==='done'){
      NH.VSTAT=done.result || {state:'done'};
      paintVStatus();
      if(NH.VIEW_MODE==='lrc') NH.loadWave(true);
    }else{
      NH.VSTAT={state:done.state==='canceled'?'canceled':'failed',
                error:done.error || (done.state==='canceled'?'已取消':'人声分离失败')};
      paintVStatus();
    }
  }catch(err){
    if(job) NH.VJOBS.delete(job.id);
    if(!NH.S || String(NH.S.uid)!==String(uid)){ paintVCancel(); return; }
    NH.VSTAT={state:'failed', error:err.message};
    paintVStatus();
  }
}
async function cancelVJob(rec){
  if(!vActive(rec) || rec.state==='canceling') return;
  const old=rec.state, oldStage=rec.stage;
  rec.state='canceling'; rec.stage='canceling';
  if(vCurrentJob()===rec) NH.VSTAT={state:'canceling'};
  paintVStatus();
  try{
    const r=await NH.api('/api/jobs/'+encodeURIComponent(rec.id)+'/cancel', {});
    if(!r || !r.ok) throw new Error((r&&r.error)||'取消失败');
    rec.state=(r.job&&r.job.state)||'canceling';
    rec.stage=(r.job&&(r.job.stage||r.job.state))||'canceling';
  }catch(err){
    rec.state=old; rec.stage=oldStage;
    if(vCurrentJob()===rec) NH.VSTAT={state:vStage(rec), error:err.message};
    NH.done('取消失败：'+err.message);
  }
  paintVStatus();
}
async function cancelAllVocals(){
  const jobs=vJobs(); if(!jobs.length) return;
  try{
    const r=await NH.api('/api/jobs/cancel_all',{kind:'vocals'});
    if(!r || !r.ok) throw new Error((r&&r.error)||'取消失败');
    for(const j of jobs){ j.state='canceling'; j.stage='canceling'; }
    if(vCurrentJob()) NH.VSTAT={state:'canceling'};
    paintVStatus();
  }catch(err){
    NH.done('取消失败：'+err.message);
  }
}
document.getElementById('vcancelall').onclick=cancelAllVocals;
(function bindVList(){
  const chip=document.getElementById('vchip'), bg=document.getElementById('vbackground'),
        box=document.getElementById('vtasks'), wrap=document.getElementById('vtaskwrap');
  if(!chip || !bg || !box || !wrap) return;
  [chip,bg].forEach(el=>{
    el.addEventListener('mouseenter',()=>{ if(vJobs().length) openVTasks(false); });
    el.addEventListener('mouseleave',scheduleCloseVTasks);
    el.addEventListener('click',e=>{ e.stopPropagation();
      if(!vJobs().length) return;
      if(NH.VLIST_PIN) closeVTasks(true);
      else openVTasks(true);
    });
  });
  box.addEventListener('mouseenter',()=>clearTimeout(NH.VLIST_T));
  box.addEventListener('mouseleave',scheduleCloseVTasks);
  box.addEventListener('click',e=>e.stopPropagation());
  document.getElementById('vtasklist').addEventListener('click',e=>{
    const b=e.target.closest('button[data-vcancel]'); if(!b) return;
    const rec=NH.VJOBS.get(b.dataset.vcancel); if(rec) cancelVJob(rec);
  });
  document.addEventListener('click',e=>{ if(!e.target.closest('#vtaskwrap')) closeVTasks(true); });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape') closeVTasks(true); });
})();


async function refreshActiveVJobs(){
  try{
    const r=await api('/api/jobs/active');
    if(!r || !r.ok) return;
    const ids=new Set();
    for(const j of (r.jobs||[])){
      ids.add(j.id);
      NH.VJOBS.set(j.id, {id:j.id, uid:String(j.key||''), state:j.state,
                           stage:j.stage || j.state});
    }
    for(const id of [...NH.VJOBS.keys()]) if(!ids.has(id)) NH.VJOBS.delete(id);
    if(NH.S){
      const cur=vCurrentJob();
      if(cur && (!NH.VSTAT || NH.VSTAT_IDX!==String(NH.S.uid))){
        NH.VSTAT={state:vStage(cur)};
        NH.VSTAT_IDX=String(NH.S.uid);
      }
    }
    NH.paintVStatus?.();
  }catch(e){}
}

NH.startVocals=startVocals;
NH.paintVStatus=paintVStatus;
NH.paintVCancel=paintVCancel;
NH.renderVTasks=renderVTasks;
NH.openVTasks=openVTasks;
NH.closeVTasks=closeVTasks;
NH.refreshActiveVJobs=refreshActiveVJobs;
refreshActiveVJobs().catch(()=>{});
})();
