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
  const starts = [];
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
      const src = {buffer: null, playbackRate: {value: 1}, connect() {},
        start() { starts.push(src); }, stop() {}, disconnect() {}};
      return src;
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
  vm.runInNewContext(fs.readFileSync('src/momo_player/static/05-audio.js', 'utf8'), ctx);
  return {engine: new ctx.window.NH.AudioEngine(), pending, signals, starts};
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


test('two concurrent plays start only one source', async () => {
  const {engine, pending, starts} = makeEngine();
  pending.set('a', deferred());
  engine.src = 'a';
  const first = engine.play();
  const second = engine.play();
  pending.get('a').resolve({name: 'a', duration: 4});
  await Promise.all([first, second]);
  assert.equal(starts.length, 1);
  assert.equal(engine._playing, true);
});

test('pause during play preload prevents automatic start', async () => {
  const {engine, pending, starts} = makeEngine();
  pending.set('a', deferred());
  engine.src = 'a';
  const play = engine.play();
  engine.pause();
  pending.get('a').resolve({name: 'a', duration: 4});
  await play;
  assert.equal(starts.length, 0);
  assert.equal(engine._playing, false);
});

test('seek before audio decode preserves the requested offset', () => {
  const {engine} = makeEngine();
  engine.src = 'a';
  engine.seek(3);
  assert.equal(engine.currentTime, 3);
  assert.equal(engine.readyState, 0);
});
