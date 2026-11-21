const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const staticDir = process.env.NIHONCO_TEST_STATIC || join(__dirname, '../src/nihonco_player/static');
const scripts = ['05-audio', '06-state', '10-app', '20-editor', '30-playback'].map(name =>
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
      if (path.startsWith('/api/jobs')) return Promise.resolve({ok: true, json: async () => ({id:'job', state:'done', result:{state:'done'}})});
      if (path === '/api/pl' && !options) return Promise.resolve({ok: true, json: async () => []});
      calls.push({path, body: options ? JSON.parse(options.body) : undefined});
      const pending = deferred();
      requests.push(pending);
      return pending.promise.then(data => ({ok: true, json: async () => data}));
    }
  });
  const run = code => vm.runInContext(code, context);
  for (const script of scripts) run(script);
  // 前端已收进 window.NH；测试通过访问器继续用短名字读写同一份状态
  run(`for (const k of Object.keys(window.NH)) {
    Object.defineProperty(globalThis, k, {
      get: () => window.NH[k], set: v => { window.NH[k] = v; }, configurable: true });
  }`);
  run(`done=msg=>messages.push(msg); loadWave=()=>{};
       S={idx:'0',uid:'u0'}; VIEW_MODE='lrc'; EROWS=[{t:1,text:'original'}];`);
  const edit = text => run(`EROWS[0].text=${JSON.stringify(text)}; markDirty()`);
  const dispatch = (type, event) => handlers.get(type).forEach(handler => handler(event));
  return {calls, requests, run, edit, dispatch, document};
}

const nextTurn = () => new Promise(resolve => setImmediate(resolve));
const song = idx => ({idx, uid: 'u' + idx, lines: [], title: 'Test song', version: 'v' + idx});

test('leaving LRC mode saves before fetching the ordinary lyrics', async () => {
  const p = player();
  p.edit('changed');
  const leaving = p.run("document.getElementById('lrcedit').onclick({})");
  assert.equal(p.calls[0]?.path, '/api/lrc');
  assert.equal(p.calls[0].body.lines[0].text, 'changed');
  assert.equal(p.run('VIEW_MODE===\'lrc\''), true);
  p.requests[0].resolve({ok: true});
  await nextTurn();
  assert.equal(p.calls[1].path, '/api/song/u0');
  p.requests[1].resolve(song('0'));
  await leaving;
  assert.equal(p.run('VIEW_MODE===\'lrc\''), false);
});

test('a failed save keeps the editor open when switching songs or modes', async () => {
  for (const action of ["load('u1')", "document.getElementById('edit').onclick()"]){
    const p = player();
    p.edit('keep this');
    const leaving = p.run(action);
    assert.equal(p.calls[0]?.path, '/api/lrc');
    p.requests[0].resolve({ok: false, error: 'disk full'});
    await nextTurn();
    assert.equal(p.calls.length, 1);
    await leaving;
    assert.equal(p.run('VIEW_MODE===\'lrc\' && EDIRTY && S.idx === "0"'), true);
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
  const leaving = p.run("load('u1')");
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
  assert.deepEqual(p.calls.map(call => call.path), ['/api/lrc', '/api/song/u1']);
  assert.equal(p.run('VIEW_MODE!==\'lrc\' && S.idx === "1"'), true);
  assert.equal(p.document.getElementById('lyr').inert, false);
});

test('an earlier song response cannot unlock a newer song transition', async () => {
  const p = player();
  const first = p.run("load('u1')");
  await nextTurn();
  const second = p.run("load('u2')");
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
  assert.equal(await p.run("load('u1')"), false);
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

test('view mode is a single mutually exclusive enum', () => {
  const p = player();
  p.run("VIEW_MODE='normal'");
  p.run("document.getElementById('edit').onclick()");
  assert.equal(p.run('VIEW_MODE'), 'kana');
  p.run("document.getElementById('edit').onclick()");
  assert.equal(p.run('VIEW_MODE'), 'normal');
});

test('save sends the loaded document version', async () => {
  const p = player();
  p.run("LRC_VERSION='v1'");
  p.edit('changed');
  const saving = p.run('saveLrc(false, true)');
  assert.equal(p.calls[0].body.version, 'v1');
  p.requests[0].resolve({ok: true, version: 'v2'});
  assert.equal(await saving, true);
  assert.equal(p.run('LRC_VERSION'), 'v2');
});

test('version conflict keeps the draft dirty', async () => {
  const p = player();
  p.run("LRC_VERSION='v1'");
  p.edit('draft');
  const saving = p.run('saveLrc(false, true)');
  p.requests[0].resolve({ok: false, conflict: true, error: '歌词已更新'});
  assert.equal(await saving, false);
  assert.equal(p.run('EDIRTY'), true);
  assert.equal(p.run("EROWS[0].text"), 'draft');
});

test('delete failure keeps the draft dirty', async () => {
  const p = player();
  p.run("window.NH.uiConfirm=async()=>true; VIEW_MODE='lrc'; LRC_VERSION='v1'; EDIRTY=true;");
  const deleting = p.run("document.getElementById('lrcfiledel').onclick()");
  await nextTurn();
  assert.equal(p.calls[0].path, '/api/lrc');
  p.requests[0].resolve({ok: false, error: 'conflict'});
  await deleting;
  assert.equal(p.run('EDIRTY'), true);
});

test('replace takes the version after pending save', async () => {
  const p = player();
  p.run("LRC_VERSION='v1'; VIEW_MODE='lrc'; SAVE_PENDING=Promise.resolve().then(()=>{LRC_VERSION='v2'; return true;});");
  const replacing = p.run("replaceLrc({action:'import_lrc',uid:'u0',text:'x'},'x',()=> 'ok')");
  await nextTurn();
  assert.equal(p.calls[0].body.version, 'v2');
  p.requests[0].resolve({ok: false, error: 'stop'});
  await replacing;
});


test('load refreshes the current document version for reset', async () => {
  const p = player();
  p.run("LRC_VERSION='old'");
  const loading = p.run("load('u1')");
  await nextTurn();
  p.requests[0].resolve(song('1'));
  await loading;
  assert.equal(p.run('LRC_VERSION'), 'v1');
});

test('delete locks song switching until the response', async () => {
  const p = player();
  p.run("window.NH.uiConfirm=async()=>true; VIEW_MODE='lrc'; EDIRTY=true;");
  const deleting = p.run("document.getElementById('lrcfiledel').onclick()");
  await nextTurn();
  assert.equal(await p.run("load('u1')"), false);
  p.requests[0].resolve({ok: false, error: 'conflict'});
  await deleting;
  assert.equal(p.run('EDIRTY'), true);
});
