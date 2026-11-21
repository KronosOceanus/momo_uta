/* 纯状态层：当前查看歌曲的加载/匹配阶段。不碰 DOM。 */
(function(){
'use strict';
const NH = window.NH || (window.NH = {});

const PHASES = Object.freeze({
  IDLE: 'idle', LOADING: 'loading', PENDING: 'pending',
  MATCHING: 'matching', READY: 'ready', FAILED: 'failed'
});

const NEXT = {
  idle:     {LOAD_START: 'loading'},
  loading:  {LOAD_START: 'loading', LOAD_READY: 'ready',
             LOAD_PENDING: 'pending', LOAD_FAILED: 'failed'},
  pending:  {LOAD_START: 'loading', MATCH_START: 'matching',
             LOAD_FAILED: 'failed'},
  matching: {LOAD_START: 'loading', MATCH_DONE: 'ready',
             MATCH_FAILED: 'failed'},
  ready:    {LOAD_START: 'loading'},
  failed:   {LOAD_START: 'loading'}
};

function initial(){
  return {phase: PHASES.IDLE, idx: null, request: 0, jobId: null, error: null};
}

function reduceView(state, ev){
  if(!state || !ev) return state;
  if(ev.type !== 'LOAD_START' && ev.request !== undefined
     && String(ev.request) !== String(state.request)) return state;
  const to = NEXT[state.phase] && NEXT[state.phase][ev.type];
  if(!to) return state;
  return {
    phase: to,
    idx: ev.idx !== undefined ? ev.idx : state.idx,
    request: ev.request !== undefined ? ev.request : state.request,
    jobId: ev.jobId !== undefined ? ev.jobId : state.jobId,
    error: ev.error || null
  };
}

NH.VIEW_PHASES = PHASES;
NH.VSTATE = initial();
NH.reduceView = reduceView;
NH.viewDispatch = ev => (NH.VSTATE = reduceView(NH.VSTATE, ev));
NH.viewPhase = () => NH.VSTATE.phase;
NH.viewMatching = () => NH.VSTATE.phase === PHASES.MATCHING;
NH.viewReady = () => NH.VSTATE.phase === PHASES.READY;
NH.viewFailed = () => NH.VSTATE.phase === PHASES.FAILED;
NH.viewCanUse = () => NH.VSTATE.phase === PHASES.READY || NH.VSTATE.phase === PHASES.FAILED;
})();
