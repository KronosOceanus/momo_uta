# SoundTouch 原调闭环

> 状态：最小可用版已接入，尚未闭环。
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

### 4.1 生成进度/取消

当前只有“生成中…”，没有进度，不能取消。

最小方案：

```text
切歌自动丢弃旧生成
可选取消按钮
```

### 4.2 缓存格式

当前 WAV 体积大。

候选：

```text
保持 WAV（简单、seek 稳定）
FLAC（无损，体积小一些）
m4a/AAC（体积小，可能有编码延迟和音质损失）
```

需要先测 seek 精度和音质。

### 4.3 长歌曲

需要测：

```text
4 分钟
8 分钟
生成耗时
内存峰值
缓存大小
```

## 5. P2：测试与文档

### 5.1 测试

```text
service 单元测试
/api/soundtouch 接口测试
缓存命中测试
失败回滚测试
时间映射测试
切歌竞态测试
```

### 5.2 文档

```text
依赖
缓存位置
非实时 DSP
LRC/波形映射规则
打包版是否支持
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
| 6 | 取消生成 | 未做 | 是否要 |
| 7 | 缓存格式 | WAV | 是否改 |
| 8 | 文档 | 部分 | 补齐 |

## 8. 当前测试基线

```text
387 Python
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
