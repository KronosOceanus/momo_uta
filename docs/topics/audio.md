# 音频引擎

> 本文说明 WebAudio 播放、预载、seek、时间和状态归属。
> 播放器状态与页面模式见 [player-state](player-state.md)。

## 0. 一句话

```text
整首音频 fetch 到内存
  → decodeAudioData
  → AudioBuffer
  → 每次播放/seek 新建 AudioBufferSourceNode
```

```text
不使用 DOM <audio> 的播放能力。
```

## 1. 为什么不用 `<audio>`

```text
<audio> 的 seek 依赖解码器 flush：
  拖动后会有静音/重缓冲
  难以保证单句循环的精确起点
```

```text
AudioBufferSourceNode：
  start(0, offset) 直接指定采样偏移
  seek = 换一个 source
  不受解码器状态影响
```

代价：

```text
整首音频必须先下载 + 解码进内存。
```

## 2. 实例

```js
const au = new NH.AudioEngine();
```

核心字段：

```text
_ctx       AudioContext
_gain      GainNode
_buf       AudioBuffer
_src       当前 AudioBufferSourceNode
_offset    暂停/seek 后的起点
_started   当前 source 的 AudioContext 起始时间
_playing
_rate
_vol / _muted
_dur
_ready     0 / 4
_url
_load      preload Promise
_loadSeq   加载序号
_abort     AbortController
_watch     requestAnimationFrame id
_ended
```

```text
AudioContext 首次播放时创建/恢复。
```

## 3. 加载

```text
au.src = '/audio/<uid>'
```

### 3.1 src 切换

```text
url 变化：
  _loadSeq++
  abort 旧请求
  _buf = null
  _ready = 0
  _dur = 0
  _offset = 0
  _load = null
  停掉旧 source
```

```text
_loadSeq 是实例内序号，不提升为全局。
```

### 3.2 preload

```text
preload()
  → 已有 _load 直接复用
  → fetch(url)
  → arrayBuffer
  → 检查 seq/url
  → decodeAudioData
  → 再检查 seq/url
  → 写 _buf
  → readyState=4
  → loadedmetadata / durationchange / canplay
```

```text
同一首歌重复 preload 只发一次请求。
```

### 3.3 取消与迟到结果

```text
切 src：
  AbortController.abort()

fetch 完成但已切歌：
  不进入 decode

decode 完成但已切歌：
  不写 _buf

旧 play 等待 preload：
  返回后发现 seq/url 变了
  → 不启动新 source
```

```text
AbortError 不当作播放失败。
```

## 4. 播放 / 暂停

### play

```text
_ctxGet()
  → 已播放则返回
  → 没 buffer 先 await preload
  → 检查 seq/url
  → _startSrc()
  → play / playing
  → 启动 watch
```

```text
play 在等待 preload 期间可能被新歌替换，
所以 await 后必须重新检查归属。
```

### pause

```text
_offset = currentTime
_stop()
emit pause
```

```text
_stop() 会清 onended、stop、disconnect。
```

## 5. seek

```text
currentTime = t
  → seek(t)
  → 更新 _offset
  → 如果在播：停旧 source，立即建新 source
  → emit seeked
```

```text
seek 是同步换 source。
更复杂的“先停、等可播、再续播”在 30-playback 的 seekPrecise。
```

### seekPrecise

```text
记录第一次 seek 前的播放状态
  → 暂停旧声音
  → 等 audioReady
  → currentTime = t
  → 等 seeked
  → 等 canplay
  → 原状态是播放则恢复 play
```

```text
连续 seek 用 NH.track('seek') 判断归属，
旧 seek 不能把播放头拉回去。
```

## 6. 时间

```text
currentTime =
  playing ? offset + (ctx.currentTime - started) * rate
          : offset
```

```text
position 由 AudioContext 时钟计算，
不是轮询 <audio>.currentTime。
```

`watch`：

```text
requestAnimationFrame
  → 约每 timeupdate_ms 发一次 timeupdate
  → 到期 dur-0.005 时：
      offset = dur
      stop
      ended = true
      timeupdate / ended / pause
```

```text
timeupdate_ms 默认 50，约 20Hz。
```

## 7. 倍速

```text
playbackRate = r
  → 播放中先结算当前位置
  → 更新 _rate
  → 当前 source.playbackRate = r
```

```text
改倍速不会重置播放位置。
当前实现音高会跟着变。
```

## 8. 音量 / 静音

```text
volume 0–1
muted bool
```

```text
两者都通过 GainNode.gain 生效。
```

```text
volume/muted 不改变 source，也不改变播放位置。
```

## 9. 与播放器状态的关系

```text
NH.PLAYING_UID
  → 当前播放源

NH.au
  → AudioEngine

NH.S
  → 当前查看页面
```

```text
commitAudio()
  → PLAYING_UID = S.uid
  → au.src = S.audio
  → au.preload()

playFromStart()
  → preload
  → 检查 S 没变
  → currentTime=0
  → play
```

```text
播放源和查看页面可以不同。
```

## 10. 歌词高亮与 offset

```text
音频 currentTime 是真实播放时间。
歌词行时间 = line.t + NH.OFFSET
```

```text
offset 只影响歌词/波形的显示对齐，
不改音频本身，也不写进音频文件。
```

## 11. 单句循环

```text
单句结束点 = 下一句起点
最后一句 = 末尾 + 8 秒
```

```text
循环跳转由 30-playback 执行：
  currentTime = 起点
  play
```

```text
AudioEngine 只负责 seek/play，不知道“单句”。
```

## 12. 错误边界

```text
fetch 非 2xx
  → “音频读取失败 <status>”
  → onerror

preload 失败
  → readyState=0
  → _load=null
  → emit error

abort / 旧 seq
  → 静默返回 null
  → 不算播放失败
```

```text
音频请求的 BrokenPipe/Reset 在 HTTP 层忽略，
因为那是前端 abort。
```

## 13. 已知限制

```text
1. 整首解码进内存，长音频内存占用高。
2. 第一次播放要等下载 + 解码。
3. 切歌会丢弃旧解码结果。
4. 改倍速音高会变。
5. seek 每次都停/起 source，连续拖动可能轻微断续。
6. AudioContext 首次创建可能受自动播放策略影响。
7. 波形只在 LRC 模式播放时逐帧刷新。
```

## 14. 测试

```text
tests/audio_engine.test.cjs
```

覆盖：

```text
切 src 会 abort 旧请求
旧 decode 不能覆盖当前 buffer
旧 play 不能启动新 source
迟到 seek 不能改当前播放
```

## 15. 相关

```text
播放器状态 → player-state.md
LRC 编辑 → lrc-editor.md
缓存 → cache.md
```
