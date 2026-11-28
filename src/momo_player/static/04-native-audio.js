/* Swift 原生音频 helper 的前端 facade。只通过 Python /api/native_audio 通信。 */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
class NativeAudioEngine {
  constructor(){
    this._url=''; this._duration=0; this._current=0; this._ready=0;
    this._playing=false; this._ended=false; this._volume=1; this._muted=false;
    this._handlers={}; this._poll=0; this._busy=false;
    this._clockAt=0; this._chain=Promise.resolve();
  }
  addEventListener(type, fn){ (this._handlers[type] ||= []).push(fn); }
  removeEventListener(type, fn){ this._handlers[type]=(this._handlers[type]||[]).filter(f=>f!==fn); }
  _emit(type){
    (this._handlers[type]||[]).forEach(f=>{ try{ f(); }catch(e){} });
    const h=this['on'+type]; if(typeof h==='function'){ try{ h(); }catch(e){} }
  }
  _headers(){
    const h={'Content-Type':'application/json'};
    const token=NH.TOKEN || (typeof window.__MOMO_TOKEN==='string'?window.__MOMO_TOKEN:'');
    if(token) h['X-Momo-Token']=token;
    return h;
  }
  _queue(fn){
    const p=this._chain.then(fn, fn);
    this._chain=p.catch(()=>{});
    return p;
  }
  async _call(action, extra){
    const r=await fetch('/api/native_audio',{method:'POST',headers:this._headers(),
      body:JSON.stringify(Object.assign({action},extra||{}))});
    let d={};
    try{ d=await r.json(); }catch(e){}
    if(!r.ok || d.ok===false) throw new Error(d.error || ('原生音频 HTTP '+r.status));
    this._apply(d);
    return d;
  }
  _now(){ return (typeof performance!=='undefined' && performance.now)
    ? performance.now() : Date.now(); }
  _apply(d){
    if(!d) return;
    if(Number.isFinite(d.duration)) this._duration=d.duration;
    if(Number.isFinite(d.current)){
      this._current=d.current; this._clockAt=this._now();
    }
    if(d.state) this._playing=d.state==='playing';
    if(typeof d.ended==='boolean') this._ended=d.ended;
    if(this._ended) this._current=this._duration;
  }
  get src(){ return this._url; }
  set src(u){
    u=String(u||'');
    if(u===this._url) return;
    this._url=u; this._duration=0; this._current=0; this._ready=0;
    this._playing=false; this._ended=false;
    this._stopPoll();
  }
  get duration(){ return this._duration; }
  get readyState(){ return this._ready; }
  get paused(){ return !this._playing; }
  get ended(){ return this._ended; }
  get currentTime(){
    if(this._playing && !this._ended){
      const dt=(this._now()-this._clockAt)/1000;
      return Math.min(this._duration||Infinity, this._current+Math.max(0,dt));
    }
    return this._current;
  }
  set currentTime(t){ this.seek(t); }
  get volume(){ return this._volume; }
  set volume(v){
    this._volume=Math.max(0,Math.min(1,+v||0));
    this._queue(()=>this._call('volume',{value:this._muted?0:this._volume})).catch(()=>{});
  }
  get muted(){ return this._muted; }
  set muted(m){
    this._muted=!!m;
    this._queue(()=>this._call('volume',{value:this._muted?0:this._volume})).catch(()=>{});
  }
  get playbackRate(){ return 1; }
  set playbackRate(_v){ /* SoundTouch 已写入音频文件；POC 不原生变速 */ }

  _load(){
    return this._call('load',{src:this._url}).then(d=>{
      this._ready=4;
      this._apply(d);
      this._emit('loadedmetadata'); this._emit('durationchange'); this._emit('canplay');
      return d;
    });
  }
  preload(){
    if(this._ready>=1) return Promise.resolve();
    if(!this._url) return Promise.resolve();
    return this._queue(()=>this._load());
  }
  async play(){
    await this.preload();
    const d=await this._queue(()=>this._call('play'));
    this._apply(d);
    this._emit('play'); this._emit('playing');
    this._startPoll();
  }
  pause(){
    this._current=this.currentTime; this._clockAt=this._now();
    this._queue(()=>this._call('pause')).catch(()=>{});
    this._playing=false; this._stopPoll(); this._emit('pause');
  }
  seek(t){
    const v=Math.max(0, Math.min(this._duration||Infinity, +t||0));
    this._current=v; this._clockAt=this._now();
    this._queue(()=>this._call('seek',{seconds:v})).catch(()=>{});
    this._emit('seeked');
  }
  _startPoll(){
    if(this._poll) return;
    this._poll=setInterval(async()=>{
      if(this._busy) return;
      this._busy=true;
      try{
        const d=await this._queue(()=>this._call('status'));
        this._emit('timeupdate');
        if(d.ended || d.state==='ended'){
          this._playing=false; this._ended=true; this._stopPoll();
          this._emit('ended'); this._emit('pause');
        }
      }catch(e){ /* 下一次轮询继续 */ }
      finally{ this._busy=false; }
    },100);
  }
  _stopPoll(){ if(this._poll){ clearInterval(this._poll); this._poll=0; } }
}
NH.NativeAudioEngine=NativeAudioEngine;
})();
