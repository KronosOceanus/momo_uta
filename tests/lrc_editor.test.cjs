const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const staticDir = process.env.MOMO_TEST_STATIC || join(__dirname, '../src/momo_player/static');
const scripts = ['05-audio', '06-state', '10-app', '11-vocals', '12-library', '20-editor', '30-playback', '40-shortcuts'].map(name =>
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
        classList: classes, textContent: '', style: {}
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

test('meta lines do not become the playback current line', () => {
  const p = player();
  p.run(`VIEW_MODE='normal';
    LINES=[{t:1,text:'作词: A',meta:true},
           {t:2,text:'第一句'},
           {t:3,text:'编曲: B',meta:true},
           {t:4,text:'第二句'}];`);
  assert.equal(p.run('idxAt(1.5)'), -1);
  assert.equal(p.run('idxAt(2.5)'), 1);
  assert.equal(p.run('idxAt(3.5)'), 1);
  assert.equal(p.run('idxAt(4.5)'), 3);
});

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
  p.requests[2].resolve({ok: true});              // 打开前先保存 redo 草稿
  await nextTurn();
  p.requests[3].resolve({ok: true, lines: [{t: 1, text: 'reopened'}]});
  await reopen;
  assert.equal(p.run('UNDO.length + REDO.length'), 0);
});

test('opening the editor keeps untimed file rows absent from playback', async () => {
  const p = player();
  p.run(`LINES=[{t:1,text:'timed'}]`);
  const opening = p.run('openLrcEditor()');
  const rows = [{t: null, text: 'draft', trans: ''}, {t: 1, text: 'timed', trans: ''}];
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
  assert.deepEqual(p.calls[1].body.lines, [{t: null, text: 'new verse', trans: ''}]);
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
  await nextTurn();
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

test('reset response does not cancel a switch already in flight', async () => {
  const p = player();
  p.run("LRC_VERSION='v0'; window.NH.uiConfirm=async()=>true;");
  const resetting = p.run("document.getElementById('resetall').onclick()");
  await nextTurn();
  const loading = p.run("load('u1')");
  await nextTurn();
  assert.equal(p.calls.length, 2);          // reset + B load
  p.requests[0].resolve({ok: true, version: 'v2'});
  await nextTurn();
  assert.equal(p.calls.length, 2);          // 不能插进 load(A)
  p.requests[1].resolve(song('1'));
  await loading;
  await resetting;
  assert.equal(p.run('S.uid'), 'u1');
});

test('translation column is opt-in and keeps the second input', () => {
  const p = player();
  p.run("TRANS_EDIT=false");
  const off = p.run("rowHtml({t:1,text:'原文',trans:'译文'},0)");
  assert.ok(!off.includes('tx trans'));
  p.run("TRANS_EDIT=true");
  const on = p.run("rowHtml({t:1,text:'原文',trans:'译文'},0)");
  assert.ok(on.includes('tx trans'));
  assert.ok(on.includes('译文'));
});

test('editing text keeps tokens fully outside the changed span', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の名前',lid:'l_aaaaaaaa',tokens:[
    {tid:'t_aaaaaaaa',start:0,end:1,base:'君',ruby:'きみ',level:'A'},
    {tid:'t_bbbbbbbb',start:1,end:2,base:'の',ruby:null,level:'K'},
    {tid:'t_cccccccc',start:2,end:4,base:'名前',ruby:'なまえ',level:'A'}]}];
    retokenizeRow(EROWS[0],'君の名');
    globalThis.__tokens = JSON.stringify(EROWS[0].tokens);
    globalThis.__payload = JSON.stringify(lrcPayload());`);
  assert.equal(p.run('EROWS[0].text'), '君の名');
  const tokens = JSON.parse(p.run('__tokens'));
  assert.deepEqual(tokens.map(t => t.tid), ['t_aaaaaaaa', 't_bbbbbbbb']);
  const payload = JSON.parse(p.run('__payload'));
  assert.equal(payload[0].lid, 'l_aaaaaaaa');
  assert.deepEqual(payload[0].tokens.map(t => [t.start, t.end, t.tid]), [
    [0, 1, 't_aaaaaaaa'], [1, 2, 't_bbbbbbbb']
  ]);
});

test('editing inside a token drops that token but shifts later tokens', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の名前を呼ぶ',tokens:[
    {tid:'t_aaaaaaaa',start:0,end:1,base:'君',ruby:'きみ',level:'A'},
    {tid:'t_bbbbbbbb',start:1,end:2,base:'の',ruby:null,level:'K'},
    {tid:'t_cccccccc',start:2,end:4,base:'名前',ruby:'なまえ',level:'A'},
    {tid:'t_dddddddd',start:4,end:5,base:'を',ruby:null,level:'K'},
    {tid:'t_eeeeeeee',start:5,end:7,base:'呼ぶ',ruby:'よぶ',level:'A'}]}];
    retokenizeRow(EROWS[0],'君の名を呼ぶ');
    globalThis.__tokens = JSON.stringify(EROWS[0].tokens);`);
  const tokens = JSON.parse(p.run('__tokens'));
  assert.deepEqual(tokens.map(t => t.tid), ['t_aaaaaaaa', 't_bbbbbbbb', 't_dddddddd', 't_eeeeeeee']);
  assert.deepEqual(tokens.at(-1), {tid:'t_eeeeeeee', start:4, end:6, base:'呼ぶ', ruby:'よぶ', level:'A'});
});

test('splitting a row moves right-side tokens to the new row', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の名前',lid:'l_aaaaaaaa',tokens:[
    {tid:'t_aaaaaaaa',start:0,end:1,base:'君'},
    {tid:'t_bbbbbbbb',start:1,end:2,base:'の'},
    {tid:'t_cccccccc',start:2,end:4,base:'名前'}]}];
    globalThis.__right = splitRow(EROWS[0], 2);
    globalThis.__state = JSON.stringify(EROWS[0]) + '|' + JSON.stringify(__right);`);
  const [left, right] = p.run('__state').split('|').map(JSON.parse);
  assert.equal(left.text, '君の');
  assert.deepEqual(left.tokens.map(t => t.tid), ['t_aaaaaaaa', 't_bbbbbbbb']);
  assert.equal(right.text, '名前');
  assert.deepEqual(right.tokens, [{tid:'t_cccccccc', start:0, end:2, base:'名前'}]);
});

test('merging rows keeps both sides token ids and shifts the right side', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の',tokens:[{tid:'t_aaaaaaaa',start:0,end:1,base:'君'}]},
                 {t:2,text:'名前',tokens:[{tid:'t_cccccccc',start:0,end:2,base:'名前'}]}];
    mergeRows(EROWS[0], ER0WS_PLACEHOLDER);`.replace('ER0WS_PLACEHOLDER', 'EROWS[1]'));
  assert.equal(p.run('EROWS[0].text'), '君の名前');
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(EROWS[0].tokens)')).map(t => [t.tid, t.start, t.end]), [
    ['t_aaaaaaaa', 0, 1], ['t_cccccccc', 2, 4]
  ]);
});

test('save response ids are merged back into matching rows', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の名'}];
    mergeSavedIds([{i:0,text:'君の名',lid:'l_aaaaaaaa',tokens:[
      {tid:'t_bbbbbbbb',start:0,end:1,base:'君'}]}]);
    globalThis.__row = JSON.stringify(EROWS[0]);`);
  assert.deepEqual(JSON.parse(p.run('__row')), {
    t: 1, text: '君の名', lid: 'l_aaaaaaaa',
    tokens: [{tid: 't_bbbbbbbb', start: 0, end: 1, base: '君'}]
  });
  p.run(`EROWS=[{t:1,text:'changed'}];
    mergeSavedIds([{i:0,text:'old',lid:'l_aaaaaaaa',tokens:[]}]);
    globalThis.__row = JSON.stringify(EROWS[0]);`);
  assert.equal(JSON.parse(p.run('__row')).lid, undefined);
});

test('split at line start keeps the content lid on the right row', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君の名',lid:'l_aaaaaaaa',tokens:[]}];
    globalThis.__right = splitRow(EROWS[0], 0);
    globalThis.__left = JSON.stringify(EROWS[0]) + '|' + JSON.stringify(__right);`);
  const [left, right] = p.run('__left').split('|').map(JSON.parse);
  assert.equal(left.text, '');
  assert.equal(right.text, '君の名');
  assert.equal(right.lid, 'l_aaaaaaaa');
  assert.notEqual(left.lid, 'l_aaaaaaaa');
});

test('merging into an empty row takes the content lid from the right row', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'',lid:'l_empty'}, {t:2,text:'君の名',lid:'l_content',tokens:[]}];
    mergeRows(EROWS[0], ER0WS_PLACEHOLDER);`.replace('ER0WS_PLACEHOLDER', 'EROWS[1]'));
  assert.equal(p.run('EROWS[0].text'), '君の名');
  assert.equal(p.run('EROWS[0].lid'), 'l_content');
});

test('one text edit burst creates one undo snapshot', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'old'}]; UNDO=[]; REDO=[]; TEXT_EDIT_ROW=null;
    beginTextEdit(0); beginTextEdit(0); beginTextEdit(0);
    globalThis.__undo = UNDO.length;`);
  assert.equal(p.run('__undo'), 1);
});

test('merge response carries ruby and level', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'君'}];
    mergeSavedIds([{i:0,text:'君',lid:'l_aaaaaaaa',tokens:[
      {tid:'t_bbbbbbbb',start:0,end:1,base:'君',ruby:'きみ',level:'A'}]}]);
    globalThis.__token = JSON.stringify(EROWS[0].tokens[0]);`);
  assert.deepEqual(JSON.parse(p.run('__token')), {
    tid:'t_bbbbbbbb', start:0, end:1, base:'君', ruby:'きみ', level:'A'
  });
});

test('save ids do not merge when the editor revision changed', async () => {
  const p = player();
  p.run(`VIEW_MODE='lrc'; S={idx:'0',uid:'u0'};
    EROWS=[{t:1,text:'old'}]; EDIRTY=true; EDIT_REVISION=0;`);
  const saving = p.run('saveLrc(true)');
  p.run(`EROWS[0].text='new'; markDirty();`);
  p.requests[0].resolve({ok:true, version:'v2', ids:[
    {i:0,text:'old',lid:'l_old',tokens:[
      {tid:'t_old',start:0,end:3,base:'old'}]}]});
  await saving;
  assert.equal(p.run('EROWS[0].text'), 'new');
  assert.equal(p.run('EROWS[0].lid'), undefined);
});

test('v2 rows mode loads, serializes and saves rows', async () => {
  const p = player();
  p.run("VIEW_MODE='lrc';");
  const opening = p.run('openLrcEditor()');
  p.requests[0].resolve({ok:true, version:'v2', model:2, rows:[
    {id:'r1', kind:'metadata', text:'[ar:X]', t:null},
    {id:'r2', kind:'lyric', text:'君', t:1, lid:'l_aaa',
     tokens:[{tid:'t_aaa',start:0,end:1,base:'君',ruby:'きみ',level:'A'}], trans:'你'},
    {id:'r3', kind:'blank', text:'', t:null},
    {id:'r4', kind:'lyric', text:'花', t:3, lid:'l_bbb', tokens:[], trans:''},
  ]});
  await opening;
  assert.equal(p.run('ROWS_MODE'), true);
  assert.equal(p.run('EROWS.length'), 4);
  assert.equal(p.run('lrcText()'), '[ar:X]\n[00:01.00]君\n\n[00:03.00]花\n');
  const saving = p.run('saveLrc(true, true)');
  assert.equal(p.calls.at(-1).body.action, 'save_rows');
  assert.equal(p.calls.at(-1).body.rows[1].lid, 'l_aaa');
  assert.equal(p.calls.at(-1).body.rows[1].trans, '你');
  p.requests[1].resolve({ok:true, version:'v3'});
  await saving;
  assert.equal(p.run('EDIRTY'), false);
});

test('split at line start gives lid, time and translation to content side', () => {
  const p = player();
  const result = p.run(`(() => {
    const row={t:1.0,text:'君',lid:'l_old',trans:'你',tokens:[]};
    const right=splitRow(row,0);
    return {leftT:row.t,leftTrans:row.trans,leftLid:row.lid,leftKind:row.kind,
            rightT:right.t,rightTrans:right.trans,rightLid:right.lid,rightKind:right.kind};
  })()`);
  assert.equal(result.leftKind, 'blank');
  assert.equal(result.leftTrans, '');
  assert.equal(result.leftT, null);
  assert.notEqual(result.leftLid, 'l_old');
  assert.equal(result.rightKind, 'lyric');
  assert.equal(result.rightTrans, '你');
  assert.equal(result.rightT, 1.0);
  assert.equal(result.rightLid, 'l_old');
});

test('clear then retype gives a new identity and empty translation', () => {
  const p = player();
  const result = p.run(`(() => {
    const row={t:1.0,text:'君',lid:'l_old',trans:'你',
               tokens:[{tid:'t1',start:0,end:1,base:'君',ruby:'きみ',level:'A'}]};
    retokenizeRow(row,'');
    const cleared={lid:row.lid,trans:row.trans,tokens:row.tokens.length,kind:row.kind};
    retokenizeRow(row,'花');
    return {cleared,lid:row.lid,trans:row.trans,tokens:row.tokens.length,kind:row.kind};
  })()`);
  assert.equal(result.cleared.kind, 'blank');
  assert.equal(result.cleared.lid, null);
  assert.equal(result.cleared.trans, '');
  assert.equal(result.cleared.tokens, 0);
  assert.equal(result.kind, 'lyric');
  assert.notEqual(result.lid, 'l_old');
  assert.equal(result.trans, '');
  assert.equal(result.tokens, 0);
});

test('applyEdit updates the version used by the next line edit', () => {
  const p = player();
  p.run(`S={idx:'0',uid:'u0',version:'v1'}; LINES=[{lid:'l_a',ruby:'',rm:'',ky:''}];`);
  p.run(`applyEdit({line:0,lid:'l_a',version:'v2',ruby:'<span></span>',rm:'',ky:''})`);
  assert.equal(p.run('S.version'), 'v2');
});

test('play mode cycles list -> one -> shuffle -> list', () => {
  const p = player();
  assert.equal(p.run('playMode'), 'list');
  p.run('cyclePlayMode()');
  assert.equal(p.run('playMode'), 'one');
  p.run('cyclePlayMode()');
  assert.equal(p.run('playMode'), 'shuffle');
  p.run('cyclePlayMode()');
  assert.equal(p.run('playMode'), 'list');
});

test('shuffle plays every song once before reshuffling', () => {
  const p = player();
  const list = ['a','b','c','d','e'];
  p.run(`window.NH.PLS=[{id:'x',items:${JSON.stringify(list.map(uid=>({uid})))} }];
         SEL_LIST='x'; PLAYING_UID='a'; setPlayMode('shuffle');`);
  assert.equal(p.run('shufflePool.length'), 4);
  assert.equal(p.run("shufflePool.includes('a')"), false);
  let cur = 'a';
  const seen = new Set(['a']);
  for(let i=0; i<4; i++){
    cur = p.run(`takeShuffleUid(${JSON.stringify(list)}, '${cur}')`);
    seen.add(cur);
  }
  assert.deepEqual([...seen].sort(), list);
  // 池空后开始新一轮，且不会立刻重复上一首
  const next = p.run(`takeShuffleUid(${JSON.stringify(list)}, '${cur}')`);
  assert.notEqual(next, cur);
});

test('next/prev line clamps at first and last', () => {
  const p = player();
  p.run(`LINES=[{t:1,text:'一'},{t:2,text:'二'},{t:3,text:'三'}]; VIEW_MODE='normal'; window.NH.au._dur=10;`);
  const at = t => p.run(`window.NH.au.currentTime=${t}; nextIdx(1)`);
  assert.equal(at(0), 0);      // before first -> first
  assert.equal(p.run('window.NH.au.currentTime=0; nextIdx(-1)'), 0);
  assert.equal(at(1), 1);
  assert.equal(p.run('window.NH.au.currentTime=1; nextIdx(-1)'), 0);
  assert.equal(at(3.5), 2);    // after/at last -> last
  assert.equal(p.run('window.NH.au.currentTime=3.5; nextIdx(-1)'), 1);
});

test('second-row target changes audio without changing viewed song', () => {
  const p = player();
  p.run(`window.NH.PLS=[{id:'x',items:[
    {uid:'a',title:'A song',artist:'A artist'},
    {uid:'b',title:'B song',artist:'B artist'}]}];
    SEL_LIST='x';
    S={idx:'1',uid:'b',title:'B song',artist:'B artist',lines:[]};
    PLAYING_UID='b';`);
  p.run("playTarget('a')");
  assert.equal(p.run('S.uid'), 'b');
  assert.equal(p.run('PLAYING_UID'), 'a');
  assert.equal(p.run('PLAY_ITEM.uid'), 'a');
  assert.match(p.document.getElementById('ttl').textContent, /A song/);
  assert.equal(p.document.getElementById('backplaying').hidden, false);
});

test('second-row follows view only when viewing the playing song', () => {
  const p = player();
  p.run(`window.NH.PLS=[{id:'x',items:[
    {uid:'a',title:'A',artist:'x'},
    {uid:'b',title:'B',artist:'x'},
    {uid:'c',title:'C',artist:'x'}]}]; SEL_LIST='x';`);
  // 查看 B，播放 A：只切音频，不改查看
  p.run(`S={idx:'1',uid:'b',title:'B',artist:'x',lines:[]}; PLAYING_UID='a';
         window.NH.load=()=>{ window.NH._loaded=true; return Promise.resolve(true); };
         window.NH._loaded=false; stepSong(1);`);
  assert.equal(p.run('S.uid'), 'b');
  assert.equal(p.run('PLAYING_UID'), 'b');
  assert.equal(p.run('window.NH._loaded'), false);
  // 查看 A，播放 A：跟随切歌
  p.run(`S={idx:'0',uid:'a',title:'A',artist:'x',lines:[]}; PLAYING_UID='a';
         window.NH._loaded=false; stepSong(1);`);
  assert.equal(p.run('window.NH._loaded'), true);
});

test('transport seek works while viewing another song', async () => {
  const p = player();
  p.run(`S={idx:'1',uid:'b',title:'B',artist:'x',lines:[]};
         PLAYING_UID='a'; window.NH.au._dur=10; window.NH.au._ready=4;
         window.NH.au._offset=0;`);
  await p.run('seekPlayback(5)');
  assert.equal(p.run('window.NH.au.currentTime'), 5);
  assert.equal(p.run('S.uid'), 'b');
});

test('failed play mode persistence rolls back', async () => {
  const p = player();
  p.run("window.NH.api=()=>Promise.resolve({ok:false,error:'disk'}); setPlayMode('one', true);");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.run('playMode'), 'list');
  assert.match(p.run('messages.at(-1)'), /disk/);
});

test('playTarget reports missing target', () => {
  const p = player();
  p.run("window.NH.done=(m)=>window.NH._msg=m; playTarget('missing-uid')");
  assert.equal(p.run('window.NH._msg'), '歌曲不可用');
});

test('editor follows normal-view line by lid or nearest time', () => {
  const p = player();
  assert.equal(p.run("editorRowIndex({lid:'l20'},[{lid:'l1'},{lid:'l20'}])"), 1);
  assert.equal(p.run("editorRowIndex({t:9.5},[{t:1},{t:8},{t:10}])"), 2);
  assert.equal(p.run("editorRowIndex({t:100},[{t:1},{t:2}])"), 1);
});

test('replace does not overwrite when draft save fails', async () => {
  const p = player();
  p.run(`VIEW_MODE='lrc'; S={idx:'0',uid:'u1',title:'X',version:'v',lines:[]};
         EROWS=[{t:1,text:'draft',trans:''}]; EDIRTY=true; LRC_VERSION='v';`);
  const replacing = p.run(`replaceLrc({action:'import_lrc',uid:'u1',text:'[00:02.00]new'},'导入中…',
                    ()=>'ok')`);
  assert.equal(p.calls[0]?.path, '/api/lrc');
  assert.equal(p.calls[0].body.action, 'save');
  p.requests[0].resolve({ok:false,error:'disk'});
  await replacing;
  assert.equal(p.calls.length, 1);          // 没有发起 import
  assert.equal(p.run('EDIRTY'), true);
});

test('openLrcEditor keeps draft when pre-open save fails', async () => {
  const p = player();
  p.run(`VIEW_MODE='lrc'; S={idx:'0',uid:'u1',title:'X',version:'v',lines:[]};
         EROWS=[{t:1,text:'draft',trans:''}]; EDIRTY=true; LRC_VERSION='v';`);
  const opening = p.run('openLrcEditor(true)');
  assert.equal(p.calls[0].body.action, 'save');
  p.requests[0].resolve({ok:false,error:'disk'});
  await opening;
  assert.equal(p.calls.length, 1);
  assert.equal(p.run('EROWS[0].text'), 'draft');
  assert.equal(p.run('EDIRTY'), true);
});

test('conflict keeps draft dirty and pauses automatic retry', async () => {
  const p = player();
  p.run("LRC_VERSION='v1'");
  p.edit('draft');
  const saving = p.run('saveLrc(true)');
  p.requests[0].resolve({ok:false, conflict:true, error:'歌词已更新'});
  assert.equal(await saving, false);
  assert.equal(p.run('EDIRTY'), true);
  assert.equal(p.run('LRC_CONFLICT'), true);
});

test('conflict reload discards local draft after confirmation', async () => {
  const p = player();
  p.run("VIEW_MODE='lrc'; EDIRTY=true; LRC_CONFLICT=true; window.NH.uiLrcConflict=async()=>'reload';");
  assert.equal(await p.run('resolveLrcConflict(false)'), true);
  assert.equal(p.run('EDIRTY'), false);
  assert.equal(p.run('LRC_CONFLICT'), false);
});

test('conflict overwrite loads new version then saves local rows', async () => {
  const p = player();
  p.run(`VIEW_MODE='lrc'; S={idx:'0',uid:'u1',title:'X',version:'v1',lines:[]};
         EROWS=[{t:1,text:'local',trans:''}]; EDIRTY=true; LRC_VERSION='v1';
         LRC_CONFLICT=true; window.NH.uiLrcConflict=async()=>true;`);
  const resolving = p.run('resolveLrcConflict(false)');
  await nextTurn();
  p.requests[0].resolve({ok:true, version:'v2'});
  await nextTurn();
  p.requests[1].resolve({ok:true, version:'v3'});
  assert.equal(await resolving, true);
  assert.equal(p.run('LRC_VERSION'), 'v3');
  assert.equal(p.run('EDIRTY'), false);
  assert.equal(p.run('EROWS[0].text'), 'local');
});

test('openLrcEditor keeps edits made while its request is in flight', async () => {
  const p = player();
  p.run(`VIEW_MODE='lrc'; S={idx:'0',uid:'u1',title:'X',version:'v',lines:[]};
         EROWS=[{t:1,text:'before',trans:''}]; EDIRTY=false;`);
  const opening = p.run('openLrcEditor(true)');
  p.edit('during');
  p.requests[0].resolve({ok:true, version:'v2', lines:[{t:1,text:'server',trans:''}]});
  assert.equal(await opening, false);
  assert.equal(p.run('EROWS[0].text'), 'during');
  assert.equal(p.run('EDIRTY'), true);
});

test('merging into an empty row falls back to the right row time', () => {
  const p = player();
  const r = p.run(`(() => {
    const cases = [
      [{t:null,text:''},{t:2,text:'君'}],
      [{t:1,text:'前'},{t:2,text:'君'}],
      [{t:null,text:'前'},{t:null,text:'君'}],
      [{t:0,text:'前'},{t:2,text:'君'}],
    ];
    return cases.map(([a,b])=>{ mergeRows(a,b); return a.t; });
  })()`);
  assert.equal(JSON.stringify(r), JSON.stringify([2, 1, null, 0]));
});

test('time order guards reject out-of-order values', () => {
  const p = player();
  const r = p.run(`(() => {
    EROWS=[{t:1,text:'a'},{t:5,text:'b'},{t:10,text:'c'}];
    return {
      ok: timeFitsRow(1,3),
      low: timeFitsRow(1,0),
      high: timeFitsRow(1,11),
      insertOk: timeFitsInsert(1,[{t:2},{t:4}]),
      insertBad: timeFitsInsert(1,[{t:6}]),
      tailBad: timeFitsInsert(3,[{t:9}]),
    };
  })()`);
  assert.equal(r.ok, true);
  assert.equal(r.low, false);
  assert.equal(r.high, false);
  assert.equal(r.insertOk, true);
  assert.equal(r.insertBad, false);
  assert.equal(r.tailBad, false);
});

test('redo clears the text edit cursor', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'old'}];
    UNDO=[JSON.stringify([{t:2,text:'undo'}])];
    REDO=[JSON.stringify([{t:3,text:'redo'}])];
    TEXT_EDIT_ROW=0; redo();`);
  assert.equal(p.run('TEXT_EDIT_ROW'), null);
});

test('translation edits are undoable and default column is on', () => {
  const p = player();
  assert.equal(p.run('TRANS_EDIT'), true);
  p.run(`EROWS=[{t:1,text:'君',trans:'old'}]; UNDO=[]; REDO=[]; TEXT_EDIT_ROW=null;
    updateTransRow({dataset:{i:0}, value:'new'});
    updateTransRow({dataset:{i:0}, value:'newer'});`);
  assert.equal(p.run('EROWS[0].trans'), 'newer');
  assert.equal(p.run('UNDO.length'), 1);
});

test('redo clamps the selected row to the restored row count', () => {
  const p = player();
  p.run(`EROWS=[{t:1,text:'a'},{t:2,text:'b'},{t:3,text:'c'}];
    ESEL=2; REDO=[JSON.stringify([{t:1,text:'only'}])];
    redo();`);
  assert.equal(p.run('ESEL'), 0);
});

test('rendering the table clears the text edit cursor', () => {
  const p = player();
  p.run("EROWS=[{t:1,text:'old'}]; TEXT_EDIT_ROW=0; renderLrcTable();");
  assert.equal(p.run('TEXT_EDIT_ROW'), null);
});

test('wave draw throttle constant is defined', () => {
  assert.match(scripts[2], /const WAVE_DRAW_MS\s*=\s*32\b/);
});

test('B returns to the playing song only when the back button is visible', () => {
  const p = player();
  const back = p.document.getElementById('backplaying');
  let clicked = 0;
  back.click = () => { clicked++; };
  back.hidden = false;
  p.dispatch('keydown', {target: {tagName: 'BODY'}, key: 'b', preventDefault() {}});
  assert.equal(clicked, 1);
  back.hidden = true;
  p.dispatch('keydown', {target: {tagName: 'BODY'}, key: 'B', preventDefault() {}});
  assert.equal(clicked, 1);
});

test('SoundTouch source always plays at 1.0 rate', () => {
  const p = player();
  p.run("ST_ON=true; ST_URL='/audio/u0?st=0.80'; ST_UID='u0'; document.getElementById('rate').value='0.80';");
  p.run("commitAudio({uid:'u0', title:'test'})");
  assert.equal(p.run('au.playbackRate'), 1);
});

test('SoundTouch mode maps source time to processed audio time', () => {
  const p = player();
  p.run("ST_ON=true; ST_SPEED=0.80; LINES=[{t:2,text:'a'},{t:4,text:'b'}]; VIEW_MODE='normal';");
  assert.equal(p.run('audioTime(2)'), 2.5);
  assert.equal(p.run('sourceTime(2.5)'), 2);
  assert.equal(p.run('idxAt(2.4)'), -1);
  assert.equal(p.run('idxAt(2.6)'), 0);
  assert.equal(p.run('idxAt(5.1)'), 1);
});

test('busy progress is replaced by a flash result without queueing', () => {
  const p = player();
  p.run("busy('生成中…')");
  assert.equal(p.run('TOAST_BUSY'), true);
  p.run("flash('已切换')");
  assert.equal(p.run('TOAST_BUSY'), false);
  assert.equal(p.document.getElementById('toast').textContent, '已切换');
});

test('stale SoundTouch generation cannot change the next song', async () => {
  const p = player();
  p.run("S={uid:'u0',title:'A'}; PLAYING_UID=null; ST_ON=false; ST_URL=null; ST_UID=null; ST_SPEED=1; document.getElementById('rate').value='0.80';");
  const pending = p.document.getElementById('rate').onchange({target:{value:'0.80'}});
  assert.equal(p.calls[0].path, '/api/soundtouch');
  p.run("S={uid:'u1',title:'B'}; cancelSoundTouch();");
  p.requests[0].resolve({ok:true, url:'/audio/u0?st=0.80'});
  await pending;
  assert.equal(p.run('ST_ON'), false);
  assert.equal(p.run('ST_URL'), null);
  assert.equal(p.run('S.uid'), 'u1');
});

test('switching the playback song resets SoundTouch speed to 1x', () => {
  const p = player();
  p.run("S={uid:'u0'}; PLAYING_UID='u0'; ST_ON=true; ST_SPEED=0.50; ST_URL='/audio/u0?st=0.50'; ST_UID='u0'; document.getElementById('rate').value='0.50'; document.getElementById('rate').disabled=true;");
  p.run("commitAudio({uid:'u1', title:'B'})");
  assert.equal(p.run('ST_ON'), false);
  assert.equal(p.run('ST_SPEED'), 1);
  assert.equal(p.run("document.getElementById('rate').value"), '1');
  assert.equal(p.run("document.getElementById('rate').disabled"), false);
});

test('failed SoundTouch generation rolls the speed slider back', async () => {
  const p = player();
  p.run("S={uid:'u0'}; PLAYING_UID='u0'; ST_ON=false; ST_URL=null; ST_UID=null; ST_SPEED=1; document.getElementById('rate').value='0.80';");
  const pending = p.document.getElementById('rate').onchange({target:{value:'0.80'}});
  assert.equal(p.calls[0].path, '/api/soundtouch');
  p.requests[0].resolve({ok:false, error:'no ffmpeg'});
  await pending;
  assert.equal(p.run('ST_ON'), false);
  assert.equal(p.run("document.getElementById('rate').value"), '1.00');
  assert.match(p.run('messages.at(-1)'), /生成失败/);
});

test('failed speed change keeps the previous active SoundTouch speed', async () => {
  const p = player();
  p.run("S={uid:'u0'}; PLAYING_UID='u0'; ST_ON=true; ST_SPEED=0.80; ST_URL='/audio/u0?st=0.80'; ST_UID='u0'; document.getElementById('rate').value='0.80';");
  const pending = p.document.getElementById('rate').onchange({target:{value:'1.25'}});
  p.requests[0].resolve({ok:false, error:'failed'});
  await pending;
  assert.equal(p.run('ST_ON'), true);
  assert.equal(p.run('ST_SPEED'), 0.80);
  assert.equal(p.run("document.getElementById('rate').value"), '0.80');
});

test('SoundTouch time mapping handles 1.25x and offset', () => {
  const p = player();
  p.run("ST_ON=true; ST_SPEED=1.25; OFFSET=1; LINES=[{t:2,text:'a'},{t:4,text:'b'}]; VIEW_MODE='normal';");
  assert.equal(p.run('sourceTime(2)'), 2.5);
  assert.equal(p.run('audioTime(3)'), 2.4);
  assert.equal(p.run('idxAt(2.4)'), 0);
  assert.equal(p.run('idxAt(4.1)'), 1);
});

test('SoundTouch wave playhead follows processed audio time', () => {
  const p = player();
  p.run("ST_ON=true; ST_SPEED=0.80; S={uid:'u0'}; PLAYING_UID='u0'; au={currentTime:4};");
  assert.equal(p.run('waveTime()'), 3.2);
});

test('seekIdx translates source lyric time into processed audio time', async () => {
  const p = player();
  p.run("ST_ON=true; ST_SPEED=0.80; OFFSET=0; VIEW_MODE='normal'; S={uid:'u0',title:'x'}; PLAYING_UID='u0'; LINES=[{t:2,text:'a'}];");
  p.run("au={paused:true,readyState:4,duration:100,currentTime:0,addEventListener(n,fn){if(n==='seeked'||n==='canplay')fn();},removeEventListener(){},pause(){},play(){return Promise.resolve();}}");
  p.run('seekIdx(0)');
  await nextTurn();
  assert.equal(p.run('au.currentTime'), 2.5);
});

test('SoundTouch time mapping also works in LRC editor mode', () => {
  const p = player();
  p.run("ST_ON=true; ST_SPEED=0.80; OFFSET=0; VIEW_MODE='lrc'; EROWS=[{t:2,text:'a'},{t:4,text:'b'}];");
  assert.equal(p.run('idxAt(2.5)'), 0);
  assert.equal(p.run('idxAt(5.1)'), 1);
});
