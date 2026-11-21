# 查看与播放：状态划分

> 读者：改播放栏、歌词区、波形、循环、重新匹配、开始按钮的人。
> 一句话：上方只操作“正在查看的歌 B”，下方只操作“正在播放的歌 A”；
> 只有上一句/下一句/单句循环会把页面带回 A；
> 播放/暂停、单曲循环属于播放器通用功能，不跳页。
> 本文是闭环：每个按钮的前置条件、动作、副作用、禁用规则都在里面。

## 0. 两个对象

```text
B = 正在查看的歌
    NH.S / NH.LINES / 左侧歌词 / 右侧面板 / LRC 表格 / 波形 / header

A = 正在播放的歌
    NH.PLAYING_UID / NH.au / 播放栏 / 播放条 / 时间 / 音量
```

```text
两个 idx 不要求相同：
  查看 B、播放 A 是正常状态
  只有 B 自己就是 A 时，两个 idx 相同
```

## 1. 状态变量

```text
NH.S           查看的歌曲载荷（idx/title/artist/lines/offset/duration）
NH.LINES       查看歌曲的歌词行
NH.PLAYING_UID 正在播放的歌曲 uid（稳定身份）
NH.au          AudioEngine，唯一出声的东西
NH.loop        单句循环开关（只属于 A）
NH.LOOP_ROW    单句循环锚定的行号
NH.loopSong    单曲循环开关（只属于 A），默认开
NH.WMARK       波形播放头，按歌曲 idx 存：{idx: seconds}
NH.MARK        最近一次打轴标记（LRC 绑定时间用）
NH.FOLLOW      波形是否跟随，默认开
NH.CUR         普通视图当前高亮行
NH.ESEL        LRC 表格当前行
```

```text
B 是否就是 A：
  NH.isSelfPlaying()
  = NH.S 存在 且 String(NH.PLAYING_UID) === String(NH.S.uid)
```

## 2. 不变量

```text
1. 只有 NH.au 出声；NH.S 只是查看对象
2. 上方按钮不 seek/pause/切 A
3. 下方按钮只操作 A；唯一例外是会把页面 load 成 A
4. 没有 PLAYING_UID：下方控件禁用；“开始”在 S 存在时仍可用
5. 单句循环只属于 A；查看别的歌时自动关闭
6. 单曲循环只属于 A；换歌不关闭
7. 开始/双击歌单永远从 0 播放
8. 双击 LRC 歌词行从该行播放
9. WMARK 只决定静止波形的播放头，不决定“开始”从哪里播
```

## 3. 控件总表（状态机）

```text
控件       条件            B==A 时                  B!=A 时
──────────────────────────────────────────────────────────────
开始       S 存在          从 0 重播                切到 B，从 0 播
上一句     PLAYING_UID 非空     A 上一句 seek            load(A) 后 A 上一句
下一句     PLAYING_UID 非空     A 下一句 seek            load(A) 后 A 下一句
播放/暂停  PLAYING_UID 非空     切 A 播放状态            切 A 播放状态
单句循环   PLAYING_UID 非空     切开关                   load(A) 后切开关
单曲循环   PLAYING_UID 非空     切开关                   只切开关，不跳页
重新匹配   S 存在           B 的候选；可能退出 LRC    B 的候选；不碰 A
LRC 模式   S 存在           进入/退出 B 的编辑       进入/退出 B 的编辑
振假名     S 存在           写 B 的 nhlrc            写 B 的 nhlrc
```

```text
“禁用”统一看 PLAYING_UID：
  上一句、播放/暂停、下一句、单句循环、单曲循环
  播放条上的播放/暂停、±10 秒、进度条

自动匹配期间额外禁用上方三个入口：
  重新匹配歌词 / 振假名编辑模式 / LRC 编辑模式
  （NH.VSTATE.phase='matching'；匹配成功/失败/结束即恢复）
```

## 4. 上方（B）

### 4.1 重新匹配歌词

```text
· 只按 B 的标题/歌手/时长搜索
· duration = B.duration（B 正在播时可用 au.duration）
· 候选、选中、写 nhlrc 都只改 B
· 不改 A 的播放位置、播放状态、歌词
· B 不在播放时，不产生任何音频动作
· LRC 编辑中点击：先退出到 B 的普通页，再搜
· 选中候选：重写 B 的 nhlrc，重新 load(B)，不自动播放
· 列表重绘后，正在播放的 ▶ 由 renderList 自己恢复
```

### 4.2 振假名选择 / 编辑

```text
· /api/line 用 B 的 idx
· 立即写 B 的 nhlrc
· 不碰 A
```

### 4.3 LRC 编辑模式

```text
所有编辑操作绑定 B。

进入：
  GET /api/lrc 读 B；不改 A；音频继续。

退出：
  load(B, autoplay=false)
  不 commitAudio，音频继续。

单击歌词行：
  · 只改 B 的选中/当前行
  · B 不在播：写 WMARK=该行时间，只重画波形
  · B 正在播：才 seek B（此时 B 就是 A）
  · 不暂停 A、不切歌

双击歌词行：
  · 切到 B（需要时 commitAudio）
  · 从该行开始播放
  · 留在 LRC 编辑模式

表格内其它操作：
  · 选行/多选：只改 SEL/ESEL，不碰音频
  · 加行/删行/改时间/改文本：只改 B
  · 保存/自动保存：只写 B 的 nhlrc
```

## 5. 下方（A）

### 5.1 开始

```text
前置：NH.S 存在
动作：
  commitAudio()          // 需要时停掉旧 A，切到 B
  playFromStart()        // 等预载 → currentTime=0 → play

效果：
  · B 暂停 → 从头播
  · B 正在播 → 从头重播
  · B 只是查看、A 在播 → 停 A，切 B，从头播
  · LRC 编辑页 → 同样从头，留在 LRC 模式
  · WMARK 不参与
```

```text
双击歌单歌曲：
  load(idx, autoplay=true)
  → commitAudio → playFromStart
  → 同样从头播

双击 LRC 歌词行：
  playLine(行号)
  → 需要时 commitAudio(B)
  → seek 到该行 → play
  → 从行位置播，不是从 0
```

### 5.2 上一句 / 下一句

```text
前置：PLAYING_UID 非空
步骤：
  1) B != A → await load(PLAYING_UID, false)   // 页面跳到 A
  2) 在 A 的歌词里算上一句/下一句
  3) seekIdx(目标行)
  4) 高亮 A 的目标行

效果：
  · A 正在播 → 跳到 A 的目标行继续播
  · A 暂停   → 跳页面并定位，保持暂停
  · B 的页面被 A 替换
  · B 有未保存 LRC → 先 flush B 再跳
```

### 5.3 播放 / 暂停

```text
前置：PLAYING_UID 非空
动作：只 toggle NH.au
效果：
  · 不切歌
  · 不跳页面
  · 不改 B 的歌词/波形/选区
  · 播放条上的 ▶/⏸ 同步
```

### 5.4 单句循环

```text
前置：PLAYING_UID 非空

点击时：
  B != A → await load(PLAYING_UID, false)       // 跳回 A
  切换 NH.loop
  打开时：LOOP_ROW = A 当前句或之后第一句
  关闭时：LOOP_ROW = -1

自动关闭：
  正在播 A、单句循环开、此时 load(B) 且 B != A
  → NH.loop=false，LOOP_ROW=-1，按钮文字同步

不自动关闭：
  · 查看 A 自己
  · 只是播放/暂停
  · 单曲循环切换
```

### 5.5 单曲循环

```text
前置：PLAYING_UID 非空
默认：开

点击时：
  只切换 NH.loopSong
  不 load(A)
  不跳页面
  不改 B 的歌词/波形/选区

行为：
  · A 自然播完 → currentTime=0 → 继续播 A
  · 换歌不关闭
  · 查看 B 时点它：页面仍停在 B

为什么它和播放/暂停同类：
  它只回答“整首播完是否重播”，
  不需要 A 的歌词页，和歌词无关。
```

### 5.6 播放条

```text
播放/暂停（play2）：
  只 toggle A；不切歌、不跳页

±10 秒：
  只 seek A；不跳页

进度条拖动：
  只 seek A；不跳页
  没有 A 时整条禁用（pointer-events:none）

音量/静音：
  只改 A 的输出，不影响任何状态机
```

## 6. 页面跳转

```text
会跳回 A 的操作：
  上一句、下一句、单句循环

不会跳页的播放器操作：
  播放/暂停、单曲循环、±10s、进度条

跳转方式：
  await load(PLAYING_UID, autoplay=false)
  · 不重新 commitAudio
  · 不打断 A
  · 不改变 A 的播放位置
  · 会把 B 替换成 A
  · B 的 LRC 编辑先 flush
```

```text
不会跳页的操作：
  播放/暂停、±10s、进度条、重新匹配、LRC 编辑
```

## 7. 波形

### 7.1 数据与时间

```text
波形数据：
  GET /api/wave/<B.idx>[?src=vocals]
  永远显示 B 的波形，不是 A 的。

时间来源 waveTime()：
  B 正在播   → NH.au.currentTime
  B 不在播   → NH.WMARK[B.idx]
  WMARK 缺失 → B 当前选中行的时间
  都没有     → NH.MARK / 0
```

```text
WMARK 是按歌曲存的：
  { "<idx>": 秒 }
  切换歌曲不会丢；切回来还在。
```

### 7.2 静止 vs 播放

```text
B 正在播：
  · 播放头跟音频
  · LRC 模式下按帧刷新
  · 波形点击/±按钮 seek B，音频继续
  · 下方播放条同步（B 就是 A）

B 不在播：
  · 波形静止
  · 播放头只随 WMARK 变化
  · 点击/±按钮只改 WMARK 和选中行
  · 不 seek A、不暂停 A、不动下方进度条
  · 只在选中/点击/缩放/平移时重画
```

### 7.3 点击与按钮

```text
点波形：
  设 WMARK = 精确点击时间
  B 在播 → seekPrecise(B)
  B 不在播 → 不碰音频
  两种情况都会选中最近的歌词行

±5s、±1s、±0.1s：
  B 在播 → seek B
  B 不在播 → 只移动 WMARK
  两种情况都会选中最近行

缩小/放大/输入窗口：
  只改 VIEW.span，不涉及音频。
```

### 7.4 跟随

```text
默认：开

跟随开：
  B 正在播 → 窗口以 au.currentTime 为中心
  B 不在播 → 窗口以 WMARK 为中心
  滚轮/双指 → 先冻结当前窗口，自动关跟随，再平移
  想回居中 → 点「跟随」重新打开

跟随关：
  窗口以 PAN_START 为起点
  滚轮/双指正常平移

点「跟随」按钮：
  开 → 关：先写 PAN_START=当前窗口起点，再关
  关 → 开：回到播放头居中
```

## 8. 禁用状态

```text
PLAYING_UID == null（从未播放过）：
  禁用：
    #prev、#play、#next
    #loop、#songloop
    #play2、#back10、#fwd10
    进度条 pointer-events:none

不禁止：
  #start（S 存在时显式载入 B 并从头播）
  重新匹配、LRC 模式、振假名编辑、音量、波形缩放

PLAYING_UID 一旦被 commitAudio 设置：
  以上控件全部恢复

没有 S（刚启动/没打开任何歌）：
  #start、重新匹配、振假名、LRC 全部 disabled
  （syncModes 启动时执行；S 载入后开始恢复）
```

## 9. 循环状态机

```text
分类：
  单句循环   和 A 的当前歌词行强相关 → 需要跳回 A 的歌词页
  单曲循环   只和整首音频是否重播有关 → 属于播放器，不跳页
```

```text
NH.loop      单句循环
NH.loopSong  单曲循环

初始：
  loop=false
  loopSong=true

事件：
  点单句循环          → 需要时跳 A；toggle loop
  load(B) 且 B != A    → loop=false；LOOP_ROW=-1
  commitAudio 切到新歌 → 同上
  点单曲循环          → 只 toggle loopSong，不跳页
  A 自然播完          → loopSong ? 从头重播 A : 停止
  查看 B              → 不改 loopSong
```

## 10. 竞态与保护

```text
LOAD_REQUEST     切歌/载入的旧响应作废
LRC_OPEN_REQUEST 多次进入编辑模式只认最后一次
SAVE_PENDING     同一时刻最多一个 LRC 保存
WAVE_SEQ         切歌后旧波形响应作废
WMARK            按 idx 存，避免 A/B 互相污染
PLAYING_UID 判定  一律 String(...) 比较
```

## 11. 实现映射

| 职责 | 位置 |
|---|---|
| 状态/载入/波形/跟随/WMARK | `static/10-app.js` |
| 时间语义/播放条/上下句/循环/开始 | `static/30-playback.js` |
| LRC 表格单击/双击/选区 | `static/20-editor.js` |
| 音频引擎 | `static/05-audio.js` |
| 载荷 duration/歌词 | `service/song.py` |
| 波形/人声 | `core/waveform.py`、`core/vocals.py` |

```text
测试：
  tests/test_player_http.py  载荷/接口
  tests/test_ui_smoke.py     真窗口冒烟
  tests/test_rematch.py      重新匹配
  tests/lrc_editor.test.cjs  前端时间/保存/锁定
```

## 12. 已知边界

```text
· B 不在播时点击 LRC 行只选行，不试听
· B 不在播时波形按钮只改 WMARK + 选中行
· B 正在播时单击 LRC 行会清掉多选（seekIdx 的现有行为）
· 双击 LRC 行会切歌并从该行播；切歌前会停 A
· 上一句/下一句会把 B 的未保存编辑 flush 后跳走
· 开始/双击歌单永远从 0，WMARK 不参与
· 单曲循环只切开关，不把页面带回 A
· 单句循环需要 A 的当前行，所以会跳回 A
```
