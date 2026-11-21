const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const code = fs.readFileSync('src/nihonco_player/static/06-state.js', 'utf8');
const ctx = {window: {}};
vm.runInNewContext(code, ctx);
const NH = ctx.window.NH;

function run(events, request = 7) {
  let s = {phase: 'idle', idx: null, request, jobId: null, error: null};
  for (const e of events) s = NH.reduceView(s, {request, ...e});
  return s;
}

test('loading -> pending -> matching -> ready', () => {
  const s = run([
    {type: 'LOAD_START', idx: 3},
    {type: 'LOAD_PENDING', idx: 3},
    {type: 'MATCH_START', idx: 3},
    {type: 'MATCH_DONE', idx: 3}
  ]);
  assert.equal(s.phase, 'ready');
  assert.equal(s.idx, 3);
});

test('matching failure opens failed state', () => {
  const s = run([
    {type: 'LOAD_START', idx: 3},
    {type: 'LOAD_PENDING', idx: 3},
    {type: 'MATCH_START', idx: 3},
    {type: 'MATCH_FAILED', idx: 3}
  ]);
  assert.equal(s.phase, 'failed');
});

test('known no match goes straight to failed', () => {
  const s = run([
    {type: 'LOAD_START', idx: 4},
    {type: 'LOAD_PENDING', idx: 4},
    {type: 'LOAD_FAILED', idx: 4}
  ]);
  assert.equal(s.phase, 'failed');
});

test('stale request cannot change current state', () => {
  const s = NH.reduceView(
    {phase: 'matching', idx: 5, request: 10, jobId: 'a', error: null},
    {type: 'MATCH_FAILED', request: 9, idx: 5}
  );
  assert.equal(s.phase, 'matching');
});

test('switch song during matching goes back to loading', () => {
  const s = run([
    {type: 'LOAD_START', idx: 1},
    {type: 'LOAD_PENDING', idx: 1},
    {type: 'MATCH_START', idx: 1},
    {type: 'LOAD_START', idx: 2}
  ]);
  assert.equal(s.phase, 'loading');
  assert.equal(s.idx, 2);
});

test('view helpers are phase-based', () => {
  const base = {idx: 1, request: 1, jobId: null, error: null};
  assert.equal(NH.reduceView({...base, phase: 'matching'}, {type: 'NOOP', request: 1}).phase, 'matching');
  assert.equal(NH.reduceView({...base, phase: 'ready'}, {type: 'NOOP', request: 1}).phase, 'ready');
});
