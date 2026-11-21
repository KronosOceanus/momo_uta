# 播放器：音频、波形与交互

> 读者：要改播放、跳转、波形、滚动、人声分离的人。
> 定位：讲清"点开一首歌到出声、到高亮、到波形"这条链路。
> 自成一体：不依赖其它文档；只引函数/类名，不写行号。

## 0. 三十秒版本

```text
点歌
  → 后端返回 {idx, title, lines[], audio, offset, pending?}
  → 前端 NH.S = 数据，渲染歌词/右侧面板
  → NH.commitAudio()：把 /audio/<uid> 交给 AudioEngine
  → AudioEngine：fetch 整个文件 → decodeAudioData → 得到一个 AudioBuffer
  → 播放 = 新建 AudioBufferSourceNode，从 _offset 处 start
  → 跳转 = 停掉旧 source → 新建 source，从新位置 start（采样级精确）

时间推进：requestAnimationFrame 里每 ~50ms 发一次 timeupdate（约 20Hz）
  → idxAt(t) 找到当前行 → 左右两栏高亮 → 波形播放头
```

```text
几个关键事实：
  · 整首歌解码进内存（4 分钟立体声约 80MB），不是流式播放
  · 跳转没有解码器 flush 问题，代价是每次都要重建 source
  · 波形由后端用 ffmpeg 预先算好峰值，前端只画
  · LRC 编辑模式下才显示波形
```

## 1. 总览与状态

### 1.1 前端状态（`window.NH`）

```text
S            当前歌曲的载荷（idx/title/artist/lines/audio/offset/pending）
LINES        歌词行（每行 t/text/ruby/rm/ky…）
NAV          每行的下标（跳转时再用 navItems() 过滤 meta 行）
CUR          当前高亮行
PLAYING_UID  正在播放的歌曲 uid
MODE         右侧面板显示 rm（罗马音）还是 ky（键位）
VIEW_MODE    normal / lrc / kana（查看模式，三者互斥）
WAVE         波形峰值数据 {duration, step, peaks, source}
VIEW         {span} 波形窗口宽度（秒）
FOLLOW       波形是否跟随播放头
PAN_START    手动平移后的窗口起点
OFFSET       整体偏移（秒，只影响歌词时间，不改音频）
VSTAT        人声分离状态（none/queued/running/done/failed）
```

### 1.2 数据流

```text
GET /api/song/<uid>
   │  载荷由 service.song.song_payload 组装
   ▼
load(i, autoplay)
   ├─ 有歌词：渲染 #lyr、右侧面板、offset、commitAudio
   └─ 无歌词：先 commitAudio 能播，再走"人声判定 → 懒匹配"（§6/§7）
   ▼
commitAudio()
   ├─ PLAYING_UID = S.uid
   ├─ au.src = S.audio || "/audio/"+S.idx
   └─ au.preload()（整首解码，异步）
   ▼
播放：au.play() 等预载完成 → 新建 source → start
```

## 2. 音频引擎

### 2.1 结构

```text
class AudioEngine
  _ctx      AudioContext（首次用时创建）
  _gain     GainNode（音量/静音）
  _buf      解码后的 AudioBuffer（整首）
  _src      当前 AudioBufferSourceNode
  _offset   当前逻辑播放位置（秒）
  _started  source 启动时的 ctx.currentTime
  _rate     播放速率
  _playing  是否正在播
  _dur      时长
  _ready    readyState（0 未载入 / 4 可播）
```

```text
时间换算：
  currentTime = _offset + (ctx.currentTime - _started) * _rate   （播放中）
  currentTime = _offset                                          （暂停/停止）
```

### 2.2 预载与解码

```text
preload()
  ① 捕获当前 _loadSeq + URL
  ② fetch(audio URL) → arrayBuffer
  ③ ctx.decodeAudioData(arrayBuffer) → buffer
  ④ 如果 _loadSeq/URL 已变 → 丢弃结果，不写 _buf/_dur，不发事件
  ⑤ 否则写 _buf/_dur/_ready，发 loadedmetadata / durationchange / canplay
  ⑥ 当前请求失败：_ready=0、_load=null、发 error；旧请求失败静默丢弃
```

```text
为什么整首解码：
  浏览器 <audio> 跳转会有解码器 flush/重缓冲，做不到"跳哪是哪"；
  AudioBufferSourceNode 从任意 offset start，天然采样级精确。

代价：
  · 内存：4 分钟 44.1kHz 立体声 float32 ≈ 80MB
  · 首次播放要等整个文件下载并解码完
  · 切歌时 src setter 会丢掉旧 _buf，交给 GC
```

### 2.3 播放 / 暂停 / 定位

```text
play()
  · 没解码就先 await preload()
  · _startSrc()：新建 source，buffer=_buf，rate=_rate，
    start(0, min(_offset, dur-0.001))
  · 发 play / playing，启动 20Hz 的 timeupdate 循环

pause()
  · _offset = currentTime；_stop()；发 pause

seek(t)
  · 夹到 [0, duration]
  · 如果正在播：_stop() → _offset=t → _startSrc()
  · 如果暂停：只改 _offset
  · 发 seeked
```

```text
_stop()：解除 onended、stop()、disconnect()、_src=null、_playing=false
```

### 2.4 前端封装的"精确定位"

```text
seekPrecise(t)：
  ① 以第一次调用时的播放状态为准（连点时不被中间态干扰）
  ② 若原来在播 → 先 pause（旧声音立刻停，画面不掉队）
  ③ 等音频就绪（audioReady：readyState≥1 或等 loadedmetadata，最多 900ms）
  ④ au.currentTime = t（触发 seek：重建 source）
  ⑤ 等 seeked（最多 900ms），必要时等 canplay
  ⑥ 原来在播 → 恢复 play
  ⑦ 用 SEEK_SEQ 丢弃过期的连续请求（只执行最后一次）
```

```text
为什么"先停再跳"：
  旧 source 会一直出声，等新位置就绪再切会听到两段声音；
  先 pause 保证听到的是"停一下 → 从新位置继续"。
```

### 2.5 变速 / 音量 / 循环

```text
变速（playbackRate setter）
  播放中改速率：先把"已播到哪里"结算进 _offset，
  再改 _rate，并同步给当前 source.playbackRate
  → 位置不跳变

音量 / 静音
  GainNode.gain = muted ? 0 : volume（0..1）

单句循环
  不是在引擎里做的，而是在 timeupdate 里：
  开启时记住 LOOP_ROW；当前时间 ≥ 下一行起点（或本行+8s）→ 跳回本行起点
```

### 2.6 事件

```text
对外发：play / playing / pause / seeked / ended /
        timeupdate / loadedmetadata / durationchange / canplay / error

前端订阅：
  播放条：timeupdate / loadedmetadata / durationchange / play / pause /
          volumechange → 重画进度条、刻度
  波形：pause / seeked / loadedmetadata 且处于 LRC 模式 → 重画
  歌单：PLAYING_UID 变化 → 列表标记 ▶
```

## 3. 波形

### 3.1 峰值：后端生成

```text
waveform.peaks(audio, source)
  ① 缓存 data/cache/wave/<md5(路径)>.<source>.<rate>.<step>.json
  ② 未命中：ffmpeg -i <audio> -ac 1 -ar <rate> -f s16le -
  ③ 每 step 秒取一次 min/max，归一化到 [-1,1]
  ④ 返回 {duration, step, peaks:[[min,max],...]}

默认（config/waveform）：
  rate = 8000   Hz
  step = 0.02   秒（20ms 一个桶）
```

```text
缓存键带 rate/step：改参数旧缓存自动失效。
source = "mix"（原曲）或 "vocals"（人声轨）。
```

### 3.2 视图模型

```text
VIEW.span        窗口宽度（秒），默认 5，范围 2–10
FOLLOW           跟随：窗口以播放头为中心
PAN_START        关闭跟随时，窗口的起点

viewStart():
  跟随：start = currentTime - span/2，夹到 [0, duration-span]
  不跟：start = clampStart(PAN_START, span)

clampStart(st, span)：把起点夹到 [0, max(0, duration-span)]
```

```text
关掉跟随时：DRAWN = 当前看到的窗口（冻结），之后平移基于它。
手动平移（滚轮/双指）自动把 FOLLOW 置为关。
```

### 3.3 绘制

```text
入口：drawWave()
  · 只画三样东西：
      绿色 min/max 竖线（波形）
      暖橙色竖线（每一行的起点）
      亮绿竖线（播放头）
  · 画布高度 = ui.wave_height（默认 120），DPR=1
  · 宽度缓存（measureCanvas），避免每帧触发布局

刷新时机：
  · LRC 模式 + 正在播：rAF 循环约 30fps
  · 暂停时：seek / 缩放 / 平移 / 切歌 / 分离完成等显式调用
```

```text
播放头位置 = (currentTime - start) / (span/宽度)
行起点位置 = (行时间 + 整体偏移 - start) / (span/宽度)
```

### 3.4 交互

```text
滚轮/双指（canvas wheel）
  取 deltaX || deltaY，换算成秒：d * span / 画布宽度
  关闭跟随，PAN_START = clampStart(当前起点 + 偏移, span)
  竖向滑动也当横向用

缩放
  缩小/放大按钮：span ±1（夹 2–10）
  点击窗口值：inline 输入，回车应用、Esc 取消、非法值还原

窗口内跳转
  左/右按钮：±span（一屏）
  ◀1s / ◀0.1s / 0.1s▶ / 1s▶：在窗口内微调

点击波形
  seekPrecise(点击处对应的时间)
  并记 MARK（打轴用）

左右成对：
  跳转与微调都走 seekPrecise；波形立即重画
```

### 3.5 人声波形

```text
loadWave(force)：
  src = （VSTAT.done 且 has_vocals）? "?src=vocals" : ""
  GET /api/wave/<uid>?src=vocals
    后端有人声轨 → 用人声轨算峰值，响应 source="vocals"
    没有 → 回退原曲，source="mix"
  提示文案：人声波形 / 原曲波形 + 时长 + 窗口
```

## 4. 时间语义与高亮

### 4.1 行时间

```text
lineT(l) = l.t + OFFSET      （t 为 null 的行不可跳转）
isMetaLine(l)：看文本（作词/作曲/编曲/制作/演唱/Lyrics…），不看字段

idxAt(t)：最后一个 lineT ≤ t 的行（可能落在 meta 行上）
NAV：全行下标；navItems() 过滤掉 meta 行，上一句/下一句只在过滤后的列表里走
```

### 4.2 高亮与滚动

```text
highlight(i)：
  LRC 模式：
    表格行加 .cur；播放中不自动滚动（打轴时滚动会晃）
    暂停时且没有多选 → scrollIntoView(nearest)
  普通模式：
    左栏 .ln 加 .on（meta 行不加）
    当前行 scrollIntoView(center)（即时，无动画）
    右栏 paint2(i)：只高亮同一行；meta 行两边都不亮
```

```text
ontimeupdate 里：
  i = idxAt(currentTime)
  只有 i 变化，或 DOM 上确实没亮时才重画（防止 UI 重建后丢高亮）
```

### 4.3 单句循环

```text
开启：LOOP_ROW = 当前行或之后第一句
每个 timeupdate：
  t ≥ 下一句起点（没有下一句则本行 +8s）→ currentTime = 本行起点
```

## 5. 歌词与右侧面板

```text
左栏：每行 <div class="ln" data-n="行号">序号 + l.ruby</div>
      ruby 由后端用引擎片段生成（含候选标记、可点的 A/AB 段）
右栏：罗马音 / 键位两页（MODE=rm/ky）
      每行一个 .ln2，点行 = 跳到该行
      高亮只跟随当前行（不是"最近的非 meta 行"）

读音编辑（普通模式）：
  点 B 档候选段（.bc），或编辑态下点可编辑段（.ew）
  → 弹层 → 选候选或手输平假名
  → POST /api/line → 后端重算该行、立即写 data/lyrics 的 nhlrc
  → 用返回的 ruby/rm/ky 更新当前行
```

```text
右上角两个 tab：罗马音 / 键位
切换只改 MODE 并重渲染右栏，不影响音频与时间。
```

## 6. 人声分离

### 6.1 触发

```text
打开任意一首歌（含 pending）→ 前端 POST /api/jobs {kind:"vocals", uid}
  配置 vocals.auto_start=false 时跳过
前端轮询 GET /api/jobs/<id>
```

### 6.2 后端流水线（串行队列）

```text
ensure(uid, audio)
  · data/vocals/<指纹>/meta.json 已存在 → 返回 done
  · 已在 queued/running → 直接返回状态（幂等）
  · 否则入队，单线程 worker 依次跑

排队：
  超过 vocals.queue_timeout_s → 标记 failed，不启动 demucs

一次分离：
  ① demucs --two-stems=vocals -n htdemucs
     （子进程；默认 HF_ENDPOINT 指镜像，避免国内卡死）
  ② 超过 vocals.run_timeout_s → kill 子进程 → failed
  ③ 取 vocals.wav → ffmpeg 转 16k 单声道
  ④ 删临时目录
  ⑤ VAD 统计 → meta.json
```

```text
VAD：
  按 frame_sec（20ms）算 RMS
  floor = 10 分位 RMS
  threshold = max(floor × floor_mult, abs_threshold)
  ratio = 超过 threshold 的帧占比
  has_vocals = ratio ≥ ratio_min（默认 0.05）
```

### 6.3 前端表现

```text
顶栏 chip：
  排队 → 人声分离：排队
  运行 → 人声分离中…
  完成 → 有人声 / 纯音乐
  失败 → 人声分离失败
LRC 模式：分离完成后自动 loadWave(true) 换成人声波形
人声缓存清理：启动时清孤儿，超过 vocals.max_bytes 按 last_used 淘汰；
临时分离文件在 data/tmp/vocals/，任务结束即删。
无歌词歌曲：分离和匹配并行；纯音乐只影响 chip/波形，不撤销已匹配歌词
```

## 7. 载入与自动匹配（pending）

```text
load(i)：
  有歌词 → 直接渲染
  没有歌词（pending）：
    ① 清空歌词，toast“匹配歌词中…”
       上方三个按钮禁用（NH.VSTATE.phase='matching'）
    ② commitAudio（能播）；autoplay 则播
    ③ 人声分离和匹配并行：
         后台 ensureVocals，chip 显示“人声分离中…”
         同时 POST /api/jobs {kind:"match", idx}
    ④ match 返回后 GET /api/song/i 一次；仍 pending 即失败
       一旦不再 pending → 重新 load，恢复按钮
    ⑤ 失败 → toast 提示没匹配到；歌词区空白，按钮恢复
```

```text
并发保护：LOAD_REQUEST 自增；每次 await 后检查 request 是否还是最新，
旧的载入流程不会覆盖新歌。
```

## 8. 提示与状态

```text
toast：
  单元素，底部居中
  busy(msg)=常驻；done(msg)=4.2 秒（可配）
  同一时刻最多排队 2 条；busy 会被 done 立即替换
  切歌、进入 LRC 模式时 clearToast()

chip：
  offchip   有偏移时显示（非 0）
  vchip     人声状态（有人声 / 纯音乐 / 分离中 / 失败）
savehint   LRC 保存状态（只在这里显示，不弹 toast）
```

## 9. 配置

```text
后端：config/defaults.json + data/config.json（本机覆盖，深层合并）
前端：web.py 把整个 config 注入 window.__CFG

用到的键：
  player.speed_min / speed_max        播放速度范围（默认 0.5–1.25，步进 0.05）
  player.ui.wave_span                 波形默认窗口（5）
  player.ui.wave_span_min/max         缩放范围（2–10）
  player.ui.wave_height               画布高度（120）
  player.ui.toast_ms                  提示时长（4200）
  player.ui.follow_default            初始是否跟随（true）
  waveform.rate / step                峰值参数（8000 / 0.02）
  vocals.*                            人声分离（模型、阈值、自动开关、镜像）
```

```text
改 ui / waveform / vocals 的参数：刷新页面或重启 app 后生效。
```

## 10. 交互与快捷键

```text
空格         播放/暂停（输入框内不拦截）
← / →        上一句 / 下一句
播放条       点击或拖动定位；±10s 按钮
速度滑块     0.5–1.25（步进 0.05）
单句循环     记住当前行，播到下一行起点跳回
重新匹配     候选只来自网络（网易云），选中后重写歌词并重新注音
全部重置     清空该歌 nhlrc 尾部，再按引擎默认重新注音
```

## 11. 已知限制

```text
① 整首解码：内存占用大，首次播放要等下载 + 解码
② 切歌会丢弃解码结果，来回切要重新解码
③ seekPrecise 每次都停/起 source：连续快速拖动会有轻微断续
④ 波形只在 LRC 模式播放时逐帧刷新；普通模式不显示波形
⑤ 波形 1x DPR、标记只有行起点，不做节拍/逐字网格
⑥ 单句循环的"本行结束"用下一行起点，最后一行固定 +8s
⑦ 人声分离串行且较慢；切歌不取消正在跑的分离；子进程超时会终止并继续队列
⑧ pending 匹配由 match 同步完成后直接重载；没有歌词即结束
```

## 12. 代码地图与测试

| 职责 | 位置 |
|---|---|
| 音频引擎 | `static/05-audio.js`（AudioEngine、au） |
| 状态/载入/波形/人声/提示 | `static/10-app.js` |
| 时间语义/播放条/高亮/循环/键盘/匹配入口 | `static/30-playback.js` |
| 波形峰值 | `core/waveform.py` |
| 人声分离 | `core/vocals.py` |
| 载荷与匹配 | `service/song.py` |
| 路由 | `http/routes.py` |

```text
测试：
  tests/test_player_http.py    接口层（载荷、改读音、保存）
  tests/test_rematch.py        候选只来自网络、选中后替换
  tests/test_vocals.py         VAD 统计与缓存路径
  tests/test_ui_smoke.py       真窗口：歌单渲染、点歌出歌词
  tests/lrc_editor.test.cjs    前端时间/保存/锁定逻辑
```
