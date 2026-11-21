const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function deferred() {
  let resolve, reject;
  const promise = new Promise((r, j) => { resolve = r; reject = j; });
  return {promise, resolve, reject};
}

function makeEngine() {
  const pending = new Map();
  const signals = new Map();
  const fetch = (url, opts={}) => {
    signals.set(url, opts.signal);
    return Promise.resolve({
      ok: true,
      arrayBuffer: async () => ({url})
    });
  };
  class FakeCtx {
    constructor() { this.currentTime = 0; this.state = 'running'; this.destination = {}; }
    createGain() { return {gain: {value: 1}, connect() {}}; }
    createBufferSource() {
      return {buffer: null, playbackRate: {value: 1}, connect() {}, start() {}, stop() {}, disconnect() {}};
    }
    decodeAudioData(ab) {
      const d = pending.get(ab.url);
      return d ? d.promise : Promise.reject(new Error('no pending ' + ab.url));
    }
  }
  const ctx = {
    window: {AudioContext: FakeCtx},
    fetch,
    AbortController,
    requestAnimationFrame() {},
  };
  vm.runInNewContext(fs.readFileSync('src/nihonco_player/static/05-audio.js', 'utf8'), ctx);
  return {engine: new ctx.window.NH.AudioEngine(), pending, signals};
}

test('late decode cannot overwrite the current source', async () => {
  const {engine, pending} = makeEngine();
  pending.set('a', deferred());
  pending.set('b', deferred());

  engine.src = 'a';
  const oldLoad = engine.preload();
  engine.src = 'b';
  const newLoad = engine.preload();

  pending.get('b').resolve({name: 'b', duration: 2});
  await newLoad;
  assert.equal(engine._buf.name, 'b');
  assert.equal(engine.duration, 2);
  assert.equal(engine.readyState, 4);

  pending.get('a').resolve({name: 'a', duration: 9});
  await oldLoad;
  assert.equal(engine._buf.name, 'b');
  assert.equal(engine.duration, 2);
});

test('switching src aborts the old audio request', async () => {
  const {engine, pending, signals} = makeEngine();
  pending.set('a', deferred());
  pending.set('b', deferred());
  engine.src = 'a';
  const oldLoad = engine.preload();
  engine.src = 'b';
  assert.equal(signals.get('a').aborted, true);
  const newLoad = engine.preload();
  pending.get('b').resolve({name: 'b', duration: 2});
  await newLoad;
  assert.equal(engine._buf.name, 'b');
  pending.get('a').resolve({name: 'a', duration: 9});
  await oldLoad;
  assert.equal(engine._buf.name, 'b');
});

test('old play does not start the new source after switching', async () => {
  const {engine, pending} = makeEngine();
  pending.set('a', deferred());
  pending.set('b', deferred());
  engine.src = 'a';
  const oldPlay = engine.play();
  engine.src = 'b';
  const newLoad = engine.preload();

  pending.get('b').resolve({name: 'b', duration: 2});
  await newLoad;
  pending.get('a').resolve({name: 'a', duration: 9});
  await oldPlay;
  assert.equal(engine._playing, false);
  assert.equal(engine._buf.name, 'b');
});

test('late completed load does not touch the current source', async () => {
  const {engine, pending} = makeEngine();
  pending.set('a', deferred());
  pending.set('b', deferred());
  engine.src = 'a';
  const oldLoad = engine.preload();
  engine.src = 'b';
  const newLoad = engine.preload();

  pending.get('b').resolve({name: 'b', duration: 3});
  await newLoad;
  pending.get('a').resolve({name: 'a', duration: 9});
  assert.equal(await oldLoad, null);
  assert.equal(engine._buf.name, 'b');
  assert.equal(engine.readyState, 4);
});
