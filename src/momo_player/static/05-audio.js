/* 命名空间模块：唯一全局是 window.NH */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});
const TIMEUPDATE_MS = 50;
// WebAudio 播放引擎：整首解码进内存，seek = 换一个 AudioBufferSourceNode
// 目的：跳转采样级精确、无解码器 flush（<audio> 做不到）
class AudioEngine {
  constructor(){
    this._ctx=null; this._gain=null; this._buf=null; this._src=null;
    this._offset=0; this._started=0; this._playing=false; this._rate=1;
    this._vol=1; this._muted=false; this._dur=0; this._ready=0; this._url='';
    this._load=null; this._loadSeq=0; this._playSeq=0; this._abort=null; this._watch=0; this._ended=false; this._handlers={};
    this.ontimeupdate=null; this.onloadedmetadata=null; this.onerror=null;
  }
  addEventListener(type, fn){ (this._handlers[type] ||= []).push(fn); }
  removeEventListener(type, fn){ this._handlers[type]=(this._handlers[type]||[]).filter(f=>f!==fn); }
  _emit(type){ (this._handlers[type]||[]).forEach(f=>{ try{ f(); }catch(e){} });
    const h=this['on'+type]; if(typeof h==='function'){ try{ h(); }catch(e){} } }

  get src(){ return this._url; }
  set src(u){
    if(u!==this._url){
      this._loadSeq++;                 // 旧 fetch/decode 完成后无权写回
      this._playSeq++;                 // 旧 play 等待期间切歌后不能启动
      if(this._abort){ try{ this._abort.abort(); }catch(e){} this._abort=null; }
      this._url=u; this._buf=null; this._ready=0; this._dur=0; this._offset=0;
      this._load=null;                 // 换歌必须重开预载，否则会拿到上一首的已解析 Promise
      this._stop();
    }
  }
  get duration(){ return this._dur; }
  get readyState(){ return this._ready; }
  get paused(){ return !this._playing; }
  get ended(){ return this._ended; }
  get currentTime(){
    if(!this._playing || !this._ctx) return this._offset;
    return Math.min(this._dur, this._offset + (this._ctx.currentTime-this._started)*this._rate);
  }
  set currentTime(t){ this.seek(t); }
  get playbackRate(){ return this._rate; }
  set playbackRate(r){
    r=+r||1;
    if(this._playing && this._ctx){          // 变速时把"已播到哪里"结算一下，避免位置跳
      this._offset=this.currentTime; this._started=this._ctx.currentTime;
    }
    this._rate=r;
    if(this._src) this._src.playbackRate.value=r;
  }
  get volume(){ return this._vol; }
  set volume(v){ this._vol=Math.max(0,Math.min(1,+v||0)); this._gainSet(); }
  get muted(){ return this._muted; }
  set muted(m){
    const v=!!m;
    if(v!==this._muted) this._diag('muted', {value:v});
    this._muted=v; this._gainSet();
  }
  _gainSet(){ if(this._gain) this._gain.gain.value=this._muted?0:this._vol; }
  _diag(kind, extra){
    try{
      const ctx=this._ctx;
      const state=ctx ? ctx.state : 'none';
      NH.reportClientError?.('audio_'+kind, kind+' state='+state, '',
        Object.assign({state, muted:this._muted, volume:this._vol,
                       playing:!this.paused}, extra||{}));
    }catch(e){}
  }
  _ctxGet(){
    if(!this._ctx){
      const C=window.AudioContext||window.webkitAudioContext;
      if(!C) throw new Error('WebAudio 不可用');
      this._ctx=new C();
      this._gain=this._ctx.createGain(); this._gain.connect(this._ctx.destination);
      this._ctx.addEventListener?.('statechange', ()=> this._diag('statechange'));
      this._diag('created');
    }
    if(this._ctx.state!=='running') this._diag('not_running');
    if(this._ctx.state==='suspended') this._ctx.resume().catch(()=>{});
    return this._ctx;
  }
  preload(){
    if(this._load) return this._load;
    const url=this._url; if(!url) return Promise.resolve();
    const seq=this._loadSeq;
    const ctl=(typeof AbortController!=='undefined') ? new AbortController() : null;
    this._abort=ctl;
    this._load=(async()=>{
      const token = window.__MOMO_TOKEN || '';
      const opts = {headers: token ? {'X-Momo-Token': token} : {}};
      if(ctl) opts.signal = ctl.signal;
      const res=await fetch(url, opts);
      if(!res.ok) throw new Error('音频读取失败 '+res.status);
      const ab=await res.arrayBuffer();
      // 下载完已切歌：不要进入 decode
      if(seq!==this._loadSeq || url!==this._url) return null;
      const ctx=this._ctxGet();
      const buf=await ctx.decodeAudioData(ab);
      if(seq!==this._loadSeq || url!==this._url) return null;   // 迟到结果丢弃
      this._buf=buf;
      this._dur=buf.duration; this._ready=4; this._ended=false;
      this._emit('loadedmetadata'); this._emit('durationchange'); this._emit('canplay');
      return buf;
    })().catch(e=>{
      const aborted=!!(e && (e.name==='AbortError' || (ctl && ctl.signal.aborted)));
      if(aborted || seq!==this._loadSeq || url!==this._url) return null; // 切歌不是加载失败
      this._ready=0; this._load=null; this._emit('error'); throw e;
    }).finally(()=>{
      if(this._abort===ctl) this._abort=null;
    });
    return this._load;
  }
  async play(){
    this._ctxGet();
    if(this._playing) return;
    const playSeq=++this._playSeq;
    const seq=this._loadSeq, url=this._url;
    if(!this._buf && url) await this.preload();
    // 等待期间切歌、暂停或另一个 play 已经接管：本次请求作废
    if(playSeq!==this._playSeq || seq!==this._loadSeq || url!==this._url || !this._buf) return;
    this._ended=false;
    this._startSrc();
    this._emit('play'); this._emit('playing'); this._watchStart();
  }
  pause(){
    this._playSeq++;
    if(!this._playing) return;
    this._offset=this.currentTime;
    this._stop();
    this._emit('pause');
  }
  seek(t){
    t=Math.max(0, +t||0);
    if(!this._buf){ this._offset=t; this._emit('seeked'); return; }
    t=Math.min(this._dur||0, t);
    const was=this._playing;
    if(was){ this._stop(); this._offset=t; this._startSrc(); }
    else this._offset=t;
    this._emit('seeked');
  }
  _startSrc(){
    const ctx=this._ctxGet();
    const s=ctx.createBufferSource();
    s.buffer=this._buf; s.playbackRate.value=this._rate; s.connect(this._gain);
    s.start(0, Math.min(this._offset, Math.max(0,this._dur-0.001)));
    this._src=s; this._playing=true; this._started=ctx.currentTime;
    this._gainSet();
  }
  _stop(){
    if(this._src){ try{ this._src.onended=null; this._src.stop(); this._src.disconnect(); }catch(e){} }
    this._src=null; this._playing=false;
  }
  _watchStart(){
    if(this._watch) return;
    let lastEmit=0;
    const tick=(ts)=>{
      if(!this._playing){ this._watch=0; return; }
      if(this.currentTime>=this._dur-0.005){
        this._offset=this._dur; this._stop(); this._ended=true;
        this._emit('timeupdate'); this._emit('ended'); this._emit('pause'); this._watch=0; return;
      }
      if(!lastEmit || ts-lastEmit>=TIMEUPDATE_MS){ this._emit('timeupdate'); lastEmit=ts; }  // ~20Hz 足够
      this._watch=requestAnimationFrame(tick);
    };
    this._watch=requestAnimationFrame(tick);
  }
}
const au = new AudioEngine();

function audioLifecycle(reason){
  try{
    NH.reportClientError?.('audio_lifecycle', reason, '', {
      visibility: (typeof document!=='undefined' && document.visibilityState) || '',
      hidden: !!(typeof document!=='undefined' && document.hidden),
      state: NH.au && NH.au._ctx ? NH.au._ctx.state : 'none',
      playing: !!(NH.au && !NH.au.paused),
      muted: !!(NH.au && NH.au.muted),
      volume: NH.au ? NH.au.volume : null,
    });
  }catch(e){}
}
if(typeof document!=='undefined' && document.addEventListener){
  document.addEventListener('visibilitychange',
    ()=>audioLifecycle('visibility_'+(document.visibilityState||'unknown')));
}
if(typeof window!=='undefined' && window.addEventListener){
  window.addEventListener('focus', ()=>audioLifecycle('focus'));
  window.addEventListener('blur', ()=>audioLifecycle('blur'));
}

Object.assign(NH, {AudioEngine, au});
})();
