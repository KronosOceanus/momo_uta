# SoundTouch 原调闭环

> 状态：P0/P1/P3 已完成；真实 WebKit 手工验收已初步通过。
> 本文只定义当前流程、缺口、验收标准和待决策项。

## 1. 当前流程

```text
速度滑块
  → 速度 = 1.0
      关闭 SoundTouch，播放原始音频

  → 速度 ≠ 1.0
      applySpeed()
      → POST /api/soundtouch {uid, speed}
      → service.soundtouch.process()
          ffmpeg 解码为 44.1kHz / stereo / PCM16
          soundstretch -tempo=...
          写入 data/cache/soundtouch/<uid>-<speed>.wav
      → 返回 /audio/<uid>?st=<speed>
      → 记录当前源时间
      → commitAudio()
      → seek 到源时间对应的处理后时间
      → 恢复播放/暂停状态
```

时间映射：

```text
audioTime = sourceTime / speed
sourceTime = audioTime * speed
```

已经映射：

```text
歌词高亮
双击歌词 seek
上一句 / 下一句
单句循环
波形播放头
波形点击 seek
波形前后跳转
LRC 编辑行定位
```

## 2. 已完成的闭环部分

```text
速度非 1.0 自动启用
速度回到 1.0 自动恢复原曲
换速度保持播放位置
真正切到另一首播放时速度回到 1.00×
播放/暂停状态保持
歌词/波形按速度映射
生成期间显示 busy 提示
成功提示 2 秒
失败提示保留
```

## 3. P0：不补就不算闭环

### 3.1 生成请求竞态（已实现）

当前风险：

```text
A 歌开始生成
→ 用户切到 B
→ A 的响应回来
→ 可能覆盖 B 的状态
```

需要：

```text
每次生成带 token
token = uid + speed + request id
返回时校验当前歌曲/当前请求
过期结果直接丢弃
```

验收：

```text
生成中切歌
生成中再改速度
快速连续切歌
旧结果不改变当前音频
```

### 3.2 失败回滚（已实现）

已实现：

```text
生成失败
→ 滑块回到上一个有效速度
→ ST_ON 保持原状态
→ toast 显示失败原因
```

例如：

```text
1.0 → 0.8 失败 → 滑块回 1.00，原曲
0.8 → 1.25 失败 → 滑块回 0.80，继续 0.8 原调
```

### 3.3 缓存生命周期（已实现）

已实现：

```text
上限 2GB
按 mtime 做 LRU
命中缓存时更新 mtime
生成成功后清理
清理超过 24 小时的 momo-st-* 临时目录
make clean-cache 清理 soundtouch
```

缓存位置：

```text
data/cache/soundtouch/<uid>-<speed>.wav
```

### 3.4 依赖与发布（已实现 A）

当前依赖：

```text
ffmpeg
soundstretch
```

问题：

```text
Finder 启动的 app PATH 不一定包含 /opt/homebrew/bin
thin / full 包里没有 soundstretch
外部开发者需要 brew install
```

已按 A 实现：

```text
thin / full 都随包 soundstretch + libSoundTouch
full 随包 ffmpeg
thin 仍使用外部 ffmpeg
许可证文件随包
THIRD_PARTY_NOTICES.md 说明来源和再分发条件
```

待完成：

```text
签名 / 公证
```

### 3.5 时间映射回归（已实现）

必须重测：

```text
0.80× / 1.25×
LRC 编辑模式进入/退出
LRC 编辑器内 seek
offset 非 0
seek 到结尾
连续 seek
单句循环边界
切歌后速度仍非 1
```

验收：

```text
歌词高亮和实际声音一致
波形播放头位置一致
循环回卷位置正确
LRC 表格显示不丢失
```

## 4. P1：体验补全

### 4.1 生成进度/取消（取消已完成，进度未做）

当前：

```text
生成中… 只有 busy 提示
切歌 / 回 1.0× 会调用取消接口
后端会终止当前 ffmpeg / soundstretch 进程
旧 token 结果会被前端丢弃
```

未做：

```text
百分比进度
手动取消按钮
```

### 4.2 缓存格式（已决定保持 WAV）

当前 WAV 体积大。

候选：

```text
保持 WAV（简单、seek 稳定）
FLAC（无损，体积小一些）
m4a/AAC（体积小，可能有编码延迟和音质损失）
```

决定：

```text
保持 WAV
理由：seek 稳定、WebKit 解码最稳、2GB LRU 足够
```

### 4.3 长歌曲（已测）

4 / 8 / 10 分钟结果：

```text
首次生成 1.35–3.47 秒
热缓存 <1ms
10 分钟 0.65× WAV 约 163MB
10 分钟 0.65× AudioBuffer 估算约 326MB
取消约 56ms
HTTP 15 秒限制未触发
```

结论：

```text
生成和取消可接受
主要注意解码后的 AudioBuffer 内存
```

## 5. P2：测试与文档

### 5.1 测试（已补齐）

```text
service 单元测试          已有
/api/soundtouch 接口测试  已有
缓存命中测试              已有
失败回滚测试              已有
时间映射测试              已有
切歌竞态测试              已有
后端取消测试              已有
```

自动化基线：

```text
401 Python
87 前端
```

剩余：

```text
真实 WebKit 手工验收
```

### 5.2 文档（已补齐）

```text
依赖                    README / packaging.md
缓存位置                README
非实时 DSP              README / 本文
LRC/波形映射规则        本文
打包版是否支持          README / packaging.md
```

## 6. 建议顺序

```text
1. 生成请求 token
2. 失败回滚
3. 缓存清理 + make clean-cache
4. 时间映射回归
5. 打包方案与许可证
6. 生成进度/取消
7. 文档
```

## 7. 逐项确认清单

| 编号 | 项目 | 当前状态 | 待确认 |
|---|---|---|---|
| 1 | 生成请求 token | 已完成 | |
| 2 | 失败回滚 | 已完成 | A |
| 3 | 缓存上限 | 已完成 | 2GB LRU |
| 4 | 打包方案 | 已完成 A | thin 外部 ffmpeg |
| 5 | 时间映射回归 | 已实现 | 持续覆盖 |
| 6 | 取消生成 | 后端取消已做 | 无进度条 |
| 7 | 缓存格式 | 保持 WAV | 已定 |
| 8 | 文档 | 已完成 | 手工验收待做 |
| 9 | 代码审计 | P0-1 / P0-2 已修复 | 见第 11 节 |

## 8. 当前测试基线

```text
390 Python
80 前端
架构检查通过
前端检查通过
```

## 9. 相关文件

```text
src/momo_player/service/soundtouch.py
src/momo_player/http/routes.py
src/momo_player/static/30-playback.js
src/momo_player/static/10-app.js
src/momo_player/static/20-editor.js
src/momo_player/static/player.html
README.md
```


## 10. 手工验收清单

自动化测试通过后，还需要在真实应用里确认：

```text
[ ] 0.80× 播放，歌词高亮与声音一致
[ ] 1.25× 播放，歌词高亮与声音一致
[ ] 点击波形 seek 到正确位置
[ ] 双击歌词 seek 到正确位置
[ ] 单句循环回卷正确
[ ] LRC 编辑器进出后速度不变调
[ ] offset 非 0 时高亮正确
[ ] 生成中切歌，B 不受 A 影响
[ ] 生成失败后滑块回到有效速度
[ ] 切到另一首播放时速度回到 1.00×
[ ] thin 版检测外部 ffmpeg
[ ] full 版无需外部 ffmpeg
```

## 11. 代码审计

### P0-1 变速作用在查看歌曲，不是播放歌曲

状态：已修复。

```text
A 正在播放
单击 B 查看，A 继续播放
拖动速度
→ applySpeed 使用 NH.S = B
→ 生成 B
→ switchStAt 默认 commit B
→ 播放被切到 B
```

违反：

```text
NH.S = 查看歌曲
NH.PLAYING_UID = 播放歌曲
```

已修复：

```text
speedTarget() 优先取 PLAY_ITEM / PLAYING_UID
没有播放目标时才回退到 NH.S
switchStAt 接收目标歌曲，不默认 commit NH.S
切换后使用 seekPlayback()，按 PLAYING_UID 定位
```

### P0-2 只查看 B 会清掉 A 的 SoundTouch 状态

状态：已修复。

`load()` 只要 `changedSong` 就调用 `cancelSoundTouch()`。  
A 仍在播放处理后的 0.8× 音频时，只查看 B 会得到：

```text
声音：0.8×
ST_ON：false
ST_SPEED：1
```

导致波形、seek、歌词映射错误。

已修复：

```text
load() 查看歌曲变化不再调用 cancelSoundTouch()
只在真正切换播放歌曲时取消/重置
```

### P1 `_run` 丢失超时

状态：已修复。

`_run` 现在有 120 秒 deadline。超时会：

```text
kill 进程组
wait 回收
抛出 TimeoutError
```

### P2 `switchStAt` 失败只回滚滑块

状态：已修复。

切换前保存：

```text
ST_ON / ST_URL / ST_UID / ST_SPEED
源位置 / 播放状态
```

seek 失败时恢复旧 ST 状态、旧音频源、旧源位置和滑块。

### P3 工具权限 / cancel uid

状态：已修复。

```text
_tool 检查 os.access(X_OK)
/api/soundtouch/cancel 要求非空 uid
```

### P3-1 无播放时拖速度

已按 B 处理：

```text
没有 PLAYING_UID
→ 只更新滑块
→ 不生成
→ 不 commit
→ 下一次播放时由 commitAudio 自动应用
```

### P3-2 cancel 代次表

已按 C 处理：

```text
取消时如果该 uid 没有 pending/current
→ 立即删除代次
process 结束时清理最后一个代次
```

### P3-3 二次恢复失败

已处理：

```text
restoreST 失败
→ 尝试回到 1.00× 原曲
→ 显示“恢复失败，已回到 1.00×”
```

### 第二轮审计

已补：

```text
_stop 增加 p.wait，避免僵尸子进程
超时/取消时关闭子进程管道
P1/P2/P3 回归测试
```

第二轮结论：

```text
没有新的 P0 / P1
P3 已全部处理
```

剩余：

```text
真实 WebKit 手工验收（用户已初步确认正常）
```

## 12. 按项目整理规则复核

依据：

```text
docs/项目整理/代码精简与优化流程.md
docs/项目整理/优化.md
docs/项目整理/播放状态机审计.md
docs/项目整理/HTTP边界审计.md
docs/项目整理/启动关闭配置审计.md
docs/项目整理/打包与首次运行审计.md
```

| 编号 | 问题 | 优先级 | 状态 |
|---|---|---|---|
| 1 | 应用退出没有取消 SoundTouch 子进程 | P1 | 已完成 |
| 2 | 缓存损坏会被永久复用 | P1 | 已完成 |
| 3 | 查看 B 关闭 A 的单句循环 | P2 | 设计行为，不处理 |
| 4 | `/audio?st=` 也能触发高成本生成 | P2 | 已完成 |
| 5 | 项目整理文档和 CHANGELOG 过期 | P2 | 待处理 |
| 6 | 启动时没有清理旧 SoundTouch 临时目录 | P3 | 已完成 |
| 7 | SoundTouch 失败没有诊断日志 | P3 | 已完成 |
| 8 | 缺少退出取消/损坏缓存/循环/结尾 seek 测试 | P3 | 已完成 |

### 12.1 P1 退出取消

状态：已修复。

momo_uta_app 退出 finally 现在调用：

```text
SVC_ST.cancel()
```

会终止当前 ffmpeg / soundstretch 进程。

### 12.2 P1 损坏缓存

状态：已修复。

命中缓存时校验：

```text
双声道 / 44100 / 16-bit
帧数 > 0
文件大小足够
```

损坏：

```text
删除坏文件
→ 重新生成
```

生成后的临时 WAV 也会校验，不通过不会替换正式缓存。

前端兜底：

```text
处理后音频 preload 失败
→ 取消 SoundTouch
→ 切回原曲
→ 滑块回 1.00×
→ 提示“变速文件不可用，已回到原曲”
```

### 12.3 P2 查看 B 关闭 A 单句循环

结论：产品设计行为，不修改。

查看 B 时关闭 A 的单句循环是预期交互，  
后续不再作为缺陷跟踪。

### 12.4 P2 `/audio?st=` 生成边界

状态：已修复。

现在职责分开：

```text
POST /api/soundtouch
→ 唯一生成入口

GET /audio/<uid>?st=<speed>
→ 只读缓存
→ 未命中 404
→ 不调用 process()
```

前端 preload 404 时回退原曲。

### 12.5 P2 文档过期

需要更新：

```text
docs/项目整理/优化.md
docs/项目整理/代码审查.md
CHANGELOG.md
dist/VERSIONS.txt（重新打包后）
```

### 12.6 P3 临时目录

状态：已修复。

启动时调用：

```text
soundtouch.cleanup_startup()
```

清理超过 24 小时的 `momo-st-*` 临时目录，  
并按 2GB 上限修剪缓存。清理失败只记录日志。

### 12.7 P3 诊断日志

状态：已修复。

记录：

```text
生成失败：uid / speed / error
取消：uid
缓存损坏：uid / speed
生成成功：uid / speed / bytes / elapsed
前端 preload 失败 / 恢复失败
```


### 12.8 P3 测试缺口

状态：已补。

```text
退出取消 / 无 uid 取消
损坏缓存恢复
/audio?st 缓存命中 + Range
/audio?st 未命中不触发生成
非 1.0× 单句循环
连续 seekPlayback
2GB 上限用小的 MAX_CACHE_BYTES 模拟
```

未做：

```text
应用级退出集成测试
真实打包版冒烟
```
