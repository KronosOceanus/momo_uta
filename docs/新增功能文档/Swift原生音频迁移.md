# Swift 原生音频迁移

> 状态：POC 已实现（默认关闭，`player.ui.native_audio=true` 启用）。
> 分支：`feature/native-audio`。
> 目标：只替换音频播放层，绕过 WKWebView/WebAudio 的后台挂起问题，不重写 Python 业务和前端 UI。

## 1. 背景

当前播放链路：

```text
pywebview / WKWebView
→ static/05-audio.js
→ WebAudio AudioContext
→ AudioBufferSourceNode
→ GainNode
→ 系统输出
```

后台问题的系统日志：

```text
Failed to acquire RBS assertion 'WebKit Media Playback'
originator doesn't have entitlement
com.apple.runningboard.assertions.webkit
```

ad-hoc 包不能携带这个 restricted entitlement，  
所以后台时 WebKit 可能挂起 WebContent：

```text
AudioContext.state 仍是 running
但实际没有输出
resume() 也无法恢复
```

结论：

```text
继续补 entitlement 不是可用的 ad-hoc 路线
需要把音频输出搬出 WebKit
```

## 2. 目标与非目标

### 目标

```text
后台播放不中断
播放/暂停/seek/时间/音量可用
继续支持 SoundTouch、单句循环
继续使用现有曲库、歌词、LRC、歌单

当前人声只影响状态徽章和波形，不参与音频播放；
本迁移不新增人声播放轨。
```

### 非目标

```text
不重写 Python 后端
不重写 LRC 编辑器
不重写曲库/歌词匹配
不一次性替换 SoundTouch
不实现音频打包
```

## 3. 目标架构

```text
pywebview UI
    ↓
Python HTTP service
    ↓
Swift audio helper
    ↓
AVAudioEngine
```

职责：

```text
JS        UI、歌词、进度显示
Python    曲库解析、文件定位、SoundTouch、IPC 生命周期
Swift     解码、播放、pause、seek、时间、音量、loop
```

Swift helper 不直接读取业务数据库，  
只接收 Python 给它的本地文件路径和播放参数。

## 4. 新增 Swift 组件

建议目录：

```text
native/
  momo-audio/
    Package.swift
    Sources/
      MomoAudio/
        main.swift
        AudioEngine.swift
        IPC.swift
        Model.swift
```

第一版可以只做一个 `swiftc` CLI，  
避免过早引入复杂 Swift Package。

### 4.1 helper 能力

POC：

```text
load
play
pause
seek
status
stop
```

后续：

```text
volume
rate
pitch
loop region
```

### 4.2 核心实现

```text
AVAudioEngine
AVAudioPlayerNode
AVAudioFile
AVAudioUnitTimePitch（后续）
mainMixerNode
```

时间来源：

```text
playerNode.lastRenderTime
→ playerTime(forNodeTime:)
→ sampleTime / sampleRate
```

seek：

```text
秒 → frame
→ stop
→ scheduleSegment(startingFrame:)
→ play
```

单句循环：

```text
loopStartFrame / loopEndFrame
→ scheduleSegment(..., .loops)
```

后台保持：

```swift
ProcessInfo.processInfo.beginActivity(
    options: .userInitiatedAllowingIdleSystemSleep,
    reason: "Playing audio"
)
```

停止播放时调用 `endActivity`。

## 5. IPC

第一版建议：

```text
Python 启动 Swift helper
stdin/stdout 一行一个 JSON
```

请求：

```json
{"id": 1, "cmd": "load", "path": "/.../x.flac"}
{"id": 2, "cmd": "play"}
{"id": 3, "cmd": "seek", "seconds": 42.5}
{"id": 4, "cmd": "status"}
```

响应：

```json
{"id": 4, "ok": true, "state": "playing",
 "current": 42.5, "duration": 310.2,
 "volume": 1.0, "rate": 1.0, "pitch": 0}
```

约束：

```text
stdout 只输出 JSON
stderr 只输出诊断
Python 负责超时、重启、退出清理
helper 退出时 Python 不能挂死
```

不新增公网端口，不使用可被外部访问的 socket。

## 6. Python 接入

新增：

```text
src/momo_player/service/audio.py
```

职责：

```text
启动/停止 helper
解析当前音频文件路径
维护 helper 状态
把 status 暴露给 HTTP
```

新增 HTTP 动作，建议：

```text
POST /api/audio
  action=load|play|pause|seek|status|volume|rate|pitch|loop|stop
```

或复用 `/api/playback`。  
实现前二选一，不要同时加两套。

第一版需要和现有 API 保持兼容：

```text
/api/song
/api/wave
/api/soundtouch
/api/jobs
```

这些接口不改语义。

## 7. 前端替换点

### 7.1 05-audio.js

当前：

```text
class AudioEngine
  _ctx
  _buf
  _src
  currentTime
  play/pause/seek
```

迁移后：

```text
保留同名 facade：NH.au
内部改成调用 /api/audio
不再创建 AudioContext
```

对上层尽量保持：

```text
NH.au.currentTime
NH.au.duration
NH.au.play()
NH.au.pause()
NH.au.seek()
NH.au.volume
```

这样 `30-playback.js` 不需要一次性重写。

### 7.2 10-app.js

需要改：

```text
commitAudio()
→ 不再设置 NH.au.src / preload

load()
→ 通过 Python 让 helper load 当前路径
```

不改：

```text
NH.S
NH.LINES
歌词加载
匹配
```

### 7.3 30-playback.js

需要改：

```text
playTarget / togglePlayPause
seekPlayback / seekPrecise
currentTime 读取
applySpeed / applyKey
closeLineLoop / stepPlaying
```

不改：

```text
播放模式
随机池
上一首/下一首逻辑
歌词高亮计算
```

### 7.4 11-vocals.js

不改。

当前人声只用于：

```text
有人声状态徽章
/api/wave?src=vocals 波形
```

没有 vocals 音频播放轨。  
如果以后要支持人声独奏/混音，再单独加 helper 输入。

### 7.5 12-library.js

不改。

### 7.6 20-editor.js

不改。

### 7.7 40-shortcuts.js

快捷键仍调用 JS 播放控制。  
底层再走 Python → Swift。

## 8. 功能影响矩阵

| 功能 | 迁移前 | 迁移后 | 风险 |
|---|---|---|---|
| 播放/暂停 | WebAudio | AVAudioPlayerNode | 低 |
| seek | AudioBufferSource 重建 | scheduleSegment | 中，需帧换算 |
| 当前时间 | AudioContext.currentTime | lastRenderTime | 中，需轮询 |
| 音量 | GainNode | mainMixer.outputVolume | 低 |
| 静音 | GainNode=0 | helper volume 或 mute | 低 |
| 单句循环 | 重建 source | scheduleSegment loop | 中 |
| 倍速 | WebAudio rate / SoundTouch | SoundTouch 或 AVAudioUnitTimePitch | 高，音质需 A/B |
| 升调 | SoundTouch | SoundTouch 或 AVAudioUnitTimePitch | 高，音质需 A/B |
| SoundTouch | WebAudio 播 WAV | Swift 播本地 WAV | 中 |
| 人声状态/波形 | `/api/wave?src=vocals` | 不变 | 无 |
| 波形 | Canvas + /api/wave | 不变 | 无 |
| 歌词同步 | JS currentTime | JS 读 helper status | 中，时间源变更 |
| 后台播放 | WebKit 可能挂起 | 原生音频 | 目标，需实测 |
| App Nap | WebKit 进程 | helper beginActivity | 中 |

## 9. 分阶段迁移

### 阶段 0：Swift CLI POC

只做：

```text
load 本地文件
play
pause
seek
status
```

验收：

```text
播放 → 隐藏窗口 → 看视频 → 回来
声音不中断
```

不接 UI，不改 Python。

### 阶段 1：Python helper + JS facade

只支持原始音频：

```text
play / pause / seek / currentTime / volume
```

保留 WebAudio 作为 fallback：

```text
feature flag：NATIVE_AUDIO=1
```

验收：

```text
正常播放
seek 不乱跳
时间显示正确
后台不静音
关闭 helper 后应用可恢复
```

### 阶段 2：SoundTouch / 单句循环

接入：

```text
SoundTouch 缓存路径
loop region
```

验收：

```text
变速/变调仍可用
单句循环准确
```

当前不处理 vocals 播放轨。

### 阶段 3：原生 rate/pitch 评估

对比：

```text
SoundTouch
vs
AVAudioUnitTimePitch
```

只在不降低音质的前提下替换。

### 阶段 4：打包与清理

```text
Swift helper 放进 .app
codesign 嵌套 helper
ad-hoc 测试
Developer ID 测试
移除 WebAudio 主路径
保留 fallback 一段时间
```

## 10. 需要修改的文件

新增：

```text
native/momo-audio/...
src/momo_player/service/audio.py
docs/新增功能文档/Swift原生音频迁移.md
```

修改：

```text
src/momo_player/static/05-audio.js
src/momo_player/static/10-app.js
src/momo_player/static/30-playback.js
src/momo_player/http/routes.py
src/momo_uta_app/__main__.py（启动/停止 helper）
packaging/build.sh
packaging/momo_uta.spec
```

不改：

```text
src/momo_player/core/library.py
src/momo_player/core/lrc_files.py
src/momo_player/core/playlists.py
src/momo_player/core/lyrics.py
src/momo_player/static/20-editor.js
src/momo_yomi/*
```

## 11. 测试

### Swift helper

```text
load 不存在的文件 → 错误
play/pause 状态
seek 到 0 / duration
EOF 状态
loop 区域
```

### Python

```text
helper 启动/退出
helper 崩溃后重启
status 超时
路径不存在
SoundTouch 路径
```

### 前端

```text
play/pause
seek
音量
时间显示
单句循环
```

### 人工验收

```text
1. 播放 → 隐藏窗口 → 看视频 → 回来
2. 后台 30 分钟
3. 切歌
4. 单句循环
5. 倍速/变调
```

## 12. 风险

```text
AVAudioEngine 与 WebAudio 时间语义不同
seek 精度和循环边界需要实测
SoundTouch 与原生 TimePitch 音质不同
helper 孤儿进程
helper 崩溃导致播放状态不同步
签名/公证仍需处理
```

## 13. 回滚

保留 WebAudio 路径：

```text
NATIVE_AUDIO=0
→ 05-audio.js 继续使用现实现
```

POC 阶段不删除 WebAudio，  
确认稳定后再清理。

## 14. 结论

```text
Swift 只替换音频输出层
Python 业务、LRC、曲库、歌单不动
WebAudio 保留 fallback
先做 CLI POC，再接 UI
```

## 15. 当前 POC 实现

已落地：

```text
native/momo-audio/main.swift
native/momo-audio/build.sh
src/momo_player/static/04-native-audio.js
src/momo_player/service/native_audio.py
GET/POST /api/native_audio
packaging/build.sh
```

构建 helper：

```bash
./native/momo-audio/build.sh
```

启用：

```json
{
  "player": {
    "ui": {
      "native_audio": true
    }
  }
}
```

当前 POC 支持：

```text
load
play
pause
seek
current time
volume
```

时间显示：

```text
HTTP status 100ms 一次
currentTime 在两次 status 之间按本地时钟插值
波形播放头不再只有 10Hz
```

当前不包含：

```text
原生 rate / pitch
原生单句循环
vocals 播放轨
helper 崩溃自动降级到 WebAudio
```

打包时 helper 位于：

```text
momo-uta-*.app/Contents/Helpers/momo-audio
```
