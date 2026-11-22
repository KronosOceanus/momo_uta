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
| `NH.loopSong` | 单曲循环 |
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
  → 后台 startVocals + match job
```

```text
没有歌词不等于不能播。
```

### 3.3 播放源切换

```text
commitAudio()
  → PLAYING_UID = NH.S.uid
  → au.src = 当前歌音频
  → 切换播放源

如果播放源变了：
  → closeLineLoop()
```

```text
PLAYING_UID 可以不等于 S。
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
循环结束点：
  下一句起点
  最后一句固定 +8 秒
```

```text
换歌 / 换播放源 → closeLineLoop()
```

## 6. 单曲循环

```text
NH.loopSong = true
```

```text
只影响 ended。
不跳页。
没有播放歌曲也可以先设定。
```

```text
A 播放结束：
  如果 loopSong 开，且页面仍对应 A
  → currentTime = 0
  → 重新 play
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
```

### 7.1 进入编辑

```text
openLrcEditor
  → /api/lrc load
  → 检查 load/lrcOpen token
  → VIEW_MODE = lrc
  → EROWS 从 lines + trans 建立
  → LRC_VERSION = version
  → TRANS_EDIT = false
```

### 7.2 编辑

```text
输入原文/翻译
  → 改 EROWS
  → markDirty()
  → 自动保存

关闭翻译列
  → 只隐藏输入框
  → 不删除 EROWS[i].trans
```

### 7.3 保存

```text
saveLrc
  → 等待 SAVE_PENDING
  → 取 lrcPayload()
  → 版本校验
  → 成功后更新 LRC_VERSION
```

```text
SAVE_PENDING 是保存队列。
LRC_REPLACING 是排他锁。
两者不是请求 token。
```

### 7.4 切歌

```text
LRC 编辑中 load 其他歌
  → setLrcLocked(true)
  → flushLrc()
  → flush 失败 → 不切
  → 成功 → 请求新歌
  → finally 解锁
```

```text
LRC_REPLACING 期间 load 直接返回 false。
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

PLAYING_UID 与 S
  → 可以不同

TRANS_EDIT
  → 只影响显示，不影响 trans 数据
```

## 10. 已知边界

```text
1. VSTATE 只覆盖查看加载，不覆盖播放/编辑器。
2. 歌曲上一首/下一首会改变查看页面。
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
```
