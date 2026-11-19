const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const staticDir = process.env.NIHONCO_TEST_STATIC || join(__dirname, '../src/nihonco_player/static');
const scripts = ['05-audio', '10-app', '20-editor', '30-playback'].map(name =>
  readFileSync(join(staticDir, name + '.js'), 'utf8')
);

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}

function player() {
  const elements = new Map();
  const classes = {add() {}, remove() {}, toggle() {}};
  const handlers = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        addEventListener() {}, getContext() {}, querySelectorAll: () => [],
        classList: classes, textContent: ''
      });
      return elements.get(id);
    },
    body: {classList: classes},
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener(event, handler) {
      if (!handlers.has(event)) handlers.set(event, []);
      handlers.get(event).push(handler);
    }
  };
  const calls = [];
  const requests = [];
  const context = vm.createContext({
    document, window: {addEventListener() {}}, requestAnimationFrame() {},
    setTimeout() {}, clearTimeout() {}, messages: [],
    fetch(path, options) {
      // 播放引擎预载 / 人声状态请求不参与断言（测试环境没有这些后端）
      if (path.startsWith('/audio/')) return Promise.resolve({ok: false, status: 404,
        arrayBuffer: async () => new ArrayBuffer(0)});
      if (path.startsWith('/api/vocals')) return Promise.resolve({ok: true, json: async () => ({state:'none'})});
      if (path === '/api/pl' && !options) return Promise.resolve({ok: true, json: async () => []});
      calls.push({path, body: options ? JSON.parse(options.body) : undefined});
      const pending = deferred();
      requests.push(pending);
      return pending.promise.then(data => ({ok: true, json: async () => data}));
    }
  });
  const run = code => vm.runInContext(code, context);
  for (const script of scripts) run(script);
  run(`done=msg=>messages.push(msg); loadWave=()=>{};
       S={idx:'0'}; LRCEDIT=true; EROWS=[{t:1,text:'original'}];`);
  const edit = text => run(`EROWS[0].text=${JSON.stringify(text)}; markDirty()`);
  const dispatch = (type, event) => handlers.get(type).forEach(handler => handler(event));
  return {calls, requests, run, edit, dispatch, document};
}

const nextTurn = () => new Promise(resolve => setImmediate(resolve));
const song = idx => ({idx, lines: [], title: 'Test song'});

test('leaving LRC mode saves before fetching the ordinary lyrics', async () => {
  const p = player();
  p.edit('changed');
  const leaving = p.run("document.getElementById('lrcedit').onclick({})");
  assert.equal(p.calls[0]?.path, '/api/lrc');
  assert.equal(p.calls[0].body.lines[0].text, 'changed');
  assert.equal(p.run('LRCEDIT'), true);
  p.requests[0].resolve({ok: true});
  await nextTurn();
  assert.equal(p.calls[1].path, '/api/song/0');
  p.requests[1].resolve(song('0'));
  await leaving;
  assert.equal(p.run('LRCEDIT'), false);
});

test('a failed save keeps the editor open when switching songs or modes', async () => {
  for (const action of ["load('1')", "document.getElementById('edit').onclick()"]){
    const p = player();
    p.edit('keep this');
    const leaving = p.run(action);
    assert.equal(p.calls[0]?.path, '/api/lrc');
    p.requests[0].resolve({ok: false, error: 'disk full'});
    await nextTurn();
    assert.equal(p.calls.length, 1);
    await leaving;
    assert.equal(p.run('LRCEDIT && EDIRTY && S.idx === "0"'), true);
    assert.equal(p.run('EROWS[0].text'), 'keep this');
    assert.equal(p.document.getElementById('lyr').inert, false);
    p.document.getElementById('lrcadd').onclick();
    assert.equal(p.run('EROWS.length'), 2);
    assert.match(p.run('messages.at(-1)'), /保存失败/);
  }
});

test('saving serializes writes and leaves edits made in flight dirty', async () => {
  const p = player();
  p.edit('first');
  const first = p.run('saveLrc(true)');
  p.edit('second');
  const second = p.run('saveLrc(true)');
  assert.equal(p.calls.length, 1);
  p.requests[0].resolve({ok: true});
  await first;
  assert.equal(p.run('EDIRTY'), true);
  assert.equal(p.calls[1].body.lines[0].text, 'second');
  p.requests[1].resolve({ok: true});
  await second;
  assert.equal(p.run('EDIRTY'), false);
});

test('switching commits the focused timestamp before locking editing and fetches once', async () => {
  const p = player();
  p.document.activeElement = {
    closest: selector => selector === '#lyr',
    blur() { p.run('EROWS[0].t=4.5; markDirty()'); }
  };
  const leaving = p.run("load('1')");
  assert.equal(p.document.getElementById('lyr').inert, true);
  assert.equal(p.document.getElementById('lrcrow2').inert, true);
  assert.equal(p.calls[0].body.lines[0].t, 4.5);
  p.requests[0].resolve({ok: true});
  await nextTurn();
  p.document.getElementById('lrcadd').onclick();
  p.dispatch('keydown', {target: {tagName: 'BODY'}, key: 'Enter', preventDefault() {}});
  p.dispatch('paste', {
    target: {tagName: 'BODY'}, clipboardData: {getData: () => 'untimed'}, preventDefault() {}
  });
  assert.equal(p.run('EROWS.length'), 1);
  p.requests[1].resolve(song('1'));
  await leaving;
  assert.deepEqual(p.calls.map(call => call.path), ['/api/lrc', '/api/song/1']);
  assert.equal(p.run('!LRCEDIT && S.idx === "1"'), true);
  assert.equal(p.document.getElementById('lyr').inert, false);
});

test('an earlier song response cannot unlock a newer song transition', async () => {
  const p = player();
  const first = p.run("load('1')");
  await nextTurn();
  const second = p.run("load('2')");
  await nextTurn();
  p.requests[0].resolve(song('1'));
  assert.equal(await first, false);
  assert.equal(p.document.getElementById('lyr').inert, true);
  p.requests[1].resolve(song('2'));
  assert.equal(await second, true);
  assert.equal(p.document.getElementById('lyr').inert, false);
});

test('undo and redo mark persisted changes dirty, and history resets on open', async () => {
  const p = player();
  p.run('snapshot()');
  p.edit('changed');
  const save = p.run('saveLrc(true)');
  p.requests[0].resolve({ok: true});
  await save;
  p.run('undo()');
  assert.equal(p.run('EDIRTY && EROWS[0].text === "original"'), true);
  const undoSave = p.run('saveLrc(true)');
  p.requests[1].resolve({ok: true});
  await undoSave;
  p.run('redo()');
  assert.equal(p.run('EDIRTY && EROWS[0].text === "changed"'), true);
  const reopen = p.run('openLrcEditor()');
  p.requests[2].resolve({ok: true, lines: [{t: 1, text: 'reopened'}]});
  await reopen;
  assert.equal(p.run('UNDO.length + REDO.length'), 0);
});

test('opening the editor keeps untimed file rows absent from playback', async () => {
  const p = player();
  p.run(`LINES=[{t:1,text:'timed'}]`);
  const opening = p.run('openLrcEditor()');
  const rows = [{t: null, text: 'draft'}, {t: 1, text: 'timed'}];
  p.requests[0].resolve({ok: true, exists: true, lines: rows});
  await opening;
  assert.equal(p.run('JSON.stringify(EROWS)'), JSON.stringify(rows));
  assert.equal(p.run('lrcText()'), 'draft\n[00:01.00]timed\n');
});

test('export includes metadata outside the rows sent to save', async () => {
  const p = player();
  const opening = p.run('openLrcEditor()');
  p.requests[0].resolve({ok: true, lines: [{t: null, text: '[Chorus]'}], metadata: [
    {before: 0, text: '[ar:歌手]'}, {before: 1, text: ' [offset:500] '}
  ]});
  await opening;
  assert.equal(p.run('lrcText()'), '[ar:歌手]\n[Chorus]\n [offset:500] \n');
  p.edit('new verse');
  const saving = p.run('saveLrc(true)');
  assert.deepEqual(p.calls[1].body.lines, [{t: null, text: 'new verse'}]);
  p.requests[1].resolve({ok: true});
  await saving;
});


test('replacing lyrics waits for a sent save and blocks song transitions', async () => {
  const p = player();
  p.run('busy=()=>{}');
  p.edit('draft');
  const saving = p.run('saveLrc(true)');
  const replacing = p.run("replaceLrc({action:'restore',idx:S.idx}, 'restoring', ()=> 'restored')");
  assert.equal(await p.run("load('1')"), false);
  assert.equal(p.calls.length, 1);
  p.requests[0].resolve({ok: true});
  await saving;
  assert.equal(p.calls[1].body.action, 'restore');
  p.requests[1].resolve({ok: true});
  await nextTurn();
  assert.equal(p.calls[2].body.action, 'load');
  p.requests[2].resolve({ok: true, lines: [{t: 1, text: 'restored'}]});
  await replacing;
  assert.equal(p.run('EROWS[0].text'), 'restored');
  assert.equal(p.document.getElementById('lyr').inert, false);
});
