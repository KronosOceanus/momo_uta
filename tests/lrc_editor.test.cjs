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
  p.requests[2].resolve({ok: true, lines: [{t: 1, text: 'reopened'}]});
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
  p.run("LRC_VERSION='v0'");
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
