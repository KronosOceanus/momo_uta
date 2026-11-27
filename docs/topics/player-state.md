# 播放器状态机

> 本文说明“查看/播放/视图/编辑”四层状态。音频算法、歌词匹配、nhlrc 格式各自有专题。
> 总体边界见 [架构文档](../architecture.md)。

## 0. 一句话

```text
播放器不是一个状态机，是四层状态：
  1. 查看歌曲的加载/匹配
  2. 音频播放
  3. 页面模式
  4. LRC 草稿/保存
```

```text
四层可以组合：
  查看 B + 播放 A
  READY + LRC 编辑
  播放中 + 单句循环
```

```text
不塞进一个全局 reducer。
```

## 1. 状态总览

| 状态 | 归属 |
|---|---|
| `NH.VSTATE` | 查看歌曲的加载/匹配阶段 |
| `NH.PLAYING_UID` | 当前播放源 |
| `NH.VIEW_MODE` | `normal` / `lrc` / `kana` |
| `NH.EDIRTY` | LRC 草稿有未保存修改 |
| `NH.SAVE_PENDING` | 当前保存请求 |
| `NH.LRC_REPLACING` | 导入/恢复/删除期间 |
| `NH.LRC_LOCKED` | 编辑/flush 锁 |
| `NH.loop` / `NH.LOOP_ROW` | 单句循环 |
| `NH.playMode` | 播放模式：`list` / `one` / `shuffle` |
| `NH.TRANS_EDIT` | 翻译列开关，只影响显示 |

## 2. 查看状态机

```text
idle
  └─ LOAD_START → loading

loading
  ├─ LOAD_READY   → ready
  ├─ LOAD_PENDING → pending
  └─ LOAD_FAILED  → failed

pending
  ├─ MATCH_START → matching
  └─ LOAD_FAILED → failed

matching
  ├─ MATCH_DONE   → ready
  └─ MATCH_FAILED → failed

任意状态
  └─ LOAD_START → loading
```

### 2.1 阶段含义

| 阶段 | 含义 |
|---|---|
| `idle` | 还没选歌 |
| `loading` | 正在请求 `/api/song/<uid>` |
| `pending` | 没有歌词，但可以播放 |
| `matching` | 后台匹配中 |
| `ready` | 有歌词，可正常使用 |
| `failed` | 加载失败或明确没歌词，但仍可播放 |

```text
pending 不是失败。
matching 不是 pending。
failed 也可能有可播放音频。
```

### 2.2 事件过滤

```text
LOAD_START
  → 总是接受，递增 load request

其他事件
  → 必须匹配 VSTATE.request
```

```text
旧请求的 LOAD_READY / LOAD_FAILED / MATCH_* 不能改新状态。
```

### 2.3 典型序列

#### 有歌词

```text
LOAD_START → LOAD_READY → ready
```

#### 没有歌词，后台匹配

```text
LOAD_START → LOAD_PENDING → MATCH_START → MATCHING
  → MATCH_DONE → ready
  → MATCH_FAILED → failed
```

#### 已确认没歌词

```text
LOAD_START → LOAD_PENDING → LOAD_FAILED → failed
```

```text
failed 仍可播放；只是没有歌词。
```

## 3. 音频播放状态

```text
NH.PLAYING_UID
NH.au.paused
NH.au.currentTime
NH.au.duration
```

```text
PLAYING_UID 是播放源。
NH.S 是当前查看页面。
```

```text
查看 B，播放 A：
  NH.S = B
  NH.PLAYING_UID = A
```

### 3.1 单击 / 双击

```text
单击歌曲：
  切页面
  如果当前没有播放源，commitAudio()
  如果已有播放源，不打断旧音频

双击歌曲：
  load(uid, true)
  切页面并从头播放
```

### 3.2 pending 的播放

```text
d.pending
  → 立即 commitAudio()
  → autoplay 或当前无播放源时开始播放
  → 后台 match job
  → vocals 只在进入 LRC 编辑模式时触发
```

```text
没有歌词不等于不能播。
```

### 3.3 播放源切换

```text
commitAudio() 会把 PLAYING_UID 切到 S.uid。
播放源变化时 closeLineLoop()。
```

```text
PLAYING_UID 可以不等于 S。
音频加载/切换机制见 audio.md。
```

## 4. 页面模式

```text
VIEW_MODE = normal / lrc / kana
```

| 模式 | 页面 |
|---|---|
| `normal` | 普通歌词 |
| `lrc` | LRC 编辑表格 |
| `kana` | 振假名编辑 |

```text
VIEW_MODE 与 VSTATE 独立。
pending + normal 合法。
ready + lrc 合法。
```

```text
进入/退出 LRC 不改变 VSTATE。
```

## 5. 单句循环

```text
NH.loop       单句循环开关
NH.LOOP_ROW   锚定行
```

```text
单句循环只属于正在播放的 A。
```

```text
查看 B、播放 A，打开单句循环：
  → 先 load(A)
  → 页面回到 A
  → 再开循环
```

```text
循环跳转的采样定位见 audio.md。
```

```text
换歌 / 换播放源 → closeLineLoop()
```

## 6. 播放模式

```text
NH.playMode = 'list' | 'one' | 'shuffle'
```

默认：

```text
list
```

按钮顺序：

```text
列表循环 → 单曲循环 → 随机播放 → 列表循环
```

行为：

```text
list     ended → 下一首，末尾回第一首
one      ended → 当前歌从头播放
shuffle  ended / 上一首 / 下一首 → 从当前列表的随机池取歌
```

随机池：

```text
进入随机播放
→ 当前歌视为本轮已播放
→ 其余歌曲洗牌进池

每次取一首
→ 池空后才重新洗牌
→ 手动点歌 / 切歌单 / 列表变化会更新池
```

一轮内不会提前重复同一首。

播放模式写入本机配置：

```text
data/config.json
player.ui.play_mode
```

保存失败时回滚到切换前的模式，并提示错误。

按钮当前只切换模式，不跳页。


## 6.1 查看歌曲与播放歌曲分离

```text
NH.S          当前查看的歌曲 B
NH.PLAYING_UID 当前播放的歌曲 A
NH.PLAY_ITEM   A 的元数据
```

当 B ≠ A：

```text
顶部标题/歌词页：B
播放栏标题：A
左侧显示：回到正在播放歌曲
```

第一行：

```text
上一句 / 下一句 / 单句循环
→ 先回到 A，再操作 A
```

第二行：

```text
上一首 / 下一首 / 播放模式

如果切换前 A = B：
  → 跟随新的 A
  → 歌词页面一起切换

如果切换前 A ≠ B：
  → 只切换 A
  → 页面继续查看 B
```

点击“回到正在播放歌曲”：

```text
load(A, false)
→ 只切查看页面
→ 不重新绑定音频
→ 不重置播放位置
→ 保持暂停/播放状态
```

播放栏 ±10 秒和进度条：

```text
只操作正在播放的 A
不要求 A = B
不改变当前查看的 B
```

## 7. LRC 草稿与保存

```text
EROWS         编辑行（含 trans）
ESEL          当前行
SEL           多选行
UNDO / REDO   快照栈
EDIRTY        有未保存修改
SAVE_PENDING  当前保存请求
LRC_REPLACING 替换/恢复/删除排他锁
LRC_LOCKED    flush/保存期间禁止编辑/切歌
LRC_VERSION   nhlrc 全文件版本
S.version     普通页改读音请求/响应使用的同一版本
```

```text
进入/编辑/保存/离场的操作细节见 lrc-editor.md。
```

```text
SAVE_PENDING 是保存队列。
LRC_REPLACING 是排他锁。
两者不是请求 token。
```

普通歌词页 `Cmd+S`：

```text
只处理当前查看歌曲 NH.S
只保存缓存歌词
已有 nhlrc → 只提示，不重写
成功后更新 S.version / LRC_VERSION，并重新加载当前查看歌曲
```

## 8. 组合示例

### 8.1 查看 B，播放 A

```text
S=B
PLAYING_UID=A
isSelfPlaying()=false
```

```text
句级操作可以 load(A) 把页面带回 A。
歌曲上一首/下一首当前也会 load 目标并切页面。
```

### 8.2 pending 但仍播放

```text
VSTATE=pending
PLAYING_UID=A
au 已绑定 A
```

```text
后台匹配不阻塞播放。
```

### 8.3 LRC 编辑 + 翻译关闭

```text
VIEW_MODE=lrc
TRANS_EDIT=false
EROWS[i].trans 仍在
lrcPayload() 仍带 trans
```

```text
关闭只是 UI，不是数据删除。
```

## 9. 不变量

```text
PLAYING_UID=null
  → 播放相关控件禁用

VSTATE=matching
  → 匹配/LRC/振假名入口禁用

VSTATE=ready/failed
  → 页面可用

LRC_REPLACING
  → 不能切歌

EDIRTY
  → 离开 LRC 前必须 flush

LRC_VERSION
  → 必须对应当前文档
S.version
  → 普通页改读音成功后同步更新

PLAYING_UID 与 S
  → 可以不同

TRANS_EDIT
  → 只影响显示，不影响 trans 数据
  → 默认开启
```

## 10. 已知边界

```text
1. VSTATE 只覆盖查看加载，不覆盖播放/编辑器。
2. 上一首/下一首：
   A = B 时查看页面跟随新 A；
   A ≠ B 时只切音频，页面保持 B。
3. 单句循环会主动把页面带回 A。
4. 翻译列开关不是数据状态。
5. 歌词正/负缓存与播放器状态无关。
6. 没有统一 reducer；这是有意设计。
```

## 11. 测试

```text
tests/state_machine.test.cjs
tests/lrc_editor.test.cjs
tests/audio_engine.test.cjs
```

覆盖：

```text
idle → loading → ready
loading → pending → matching → ready/failed
旧 request 不能改新状态
LRC 保存/撤销/替换
音频 stale decode
```

## 12. 相关

```text
音频指纹 → fingerprint.md
歌词缓存 → cache.md
歌词匹配 → lyrics-matching.md
音频引擎 → audio.md
```
