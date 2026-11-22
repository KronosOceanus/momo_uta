# 缓存与持久化

> 本文回答：哪些数据能删、删了要重算什么、什么时候失效、删除/重建的代价。
> 分层与模块职责见 [架构文档](../architecture.md)。

```text
本文路径相对 data 根：
  开发：<repo>/data
  打包：~/Library/Application Support/nihonco uta/data
```

## 0. 一句话分类

```text
权威数据：删了会丢用户资产
可重建缓存：删了能重算
昂贵缓存：能重算，但不想随便删
临时文件：随时可删
```

```text
data/curated、data/lyrics、data/config.json 是权威。
data/cache、data/tmp 是缓存/临时。
data/vocals 是“可重建但昂贵”，不是权威。
```

## 1. 权威数据边界

```text
权威数据的完整表在 architecture §2。
本文不重复身份键和删除行为。
```

```text
data/curated、data/lyrics、data/config.json
  → 不是缓存，不能靠清缓存处理
```

## 2. 缓存总表

| 路径 | 键 | 写入者 | 失效方式 | 删除后 |
|---|---|---|---|---|
| `data/cache/lyrics/*.json` | title\|artist | `lyrics_fetch` | force / re-match / 删 | 重新联网 |
| `data/cache/annotations/*.json` | version + text + stored | `annotation_cache` | 源码变化 / 删 | 重新注音 |
| `data/cache/wave/*.json` | path + source + rate + step | `waveform` | size/mtime / 参数 / 删 | 重新 ffmpeg |
| `data/cache/library_index.json` | 文件路径 | `library_index` | size/mtime / 删 | 重新扫库 |
| `data/cache/fingerprints.json` | 文件路径 | `fingerprint` | size/mtime / 删 | 重新算指纹 |
| `data/vocals/<uid>/` | uid | `vocals` | 手动 / LRU | 重新 demucs（很贵） |
| `data/tmp/` | 进程/任务 | 各任务 | 任务结束 / 启动清理 | 无 |

## 3. 歌词缓存

```text
data/cache/lyrics/<md5(title|artist)>.json
```

```text
键：NFKC(title)|NFKC(artist) → md5 16 位
内容：source / lrc / tlyric / lang / kana_ratio
失败：{miss:true, reason}
```

```text
它是抓取结果，不是权威歌词。
有 .nhlrc 时，歌词缓存不参与歌词读取。
没有 .nhlrc 时，lrc 用于显示，tlyric 可配对翻译。
```

```text
删除 → 重新联网匹配。
负缓存带 checked_at，默认 7 天后过期；过期后会自动重试。
```

## 4. 注音缓存

```text
data/cache/annotations/<sha1(version|text|stored)>.json
```

```text
键：VERSION + 原始行文本 + stored 读音
值：ruby / rm / ky / rmH / kyH
```

```text
只缓存显示字段，不碰 nhlrc。
文本或 stored 改变 → 新键。
VERSION 改变 → 全部失效。
```

```text
引擎、词典、渲染规则或源码变化时，VERSION 自动变化。
```

## 5. 波形缓存

```text
data/cache/wave/<md5(path)>.<source>.<rate>.<step>.json
```

```text
键：音频路径 + mix/vocals + rate + step
内容：duration / step / audio_size / audio_mtime / peaks
```

```text
命中时校验：
  audio_size
  audio_mtime（纳秒）
```

```text
同一路径换文件 → size/mtime 变 → 旧缓存不命中。
改 rate/step → 路径键变 → 旧缓存失效。
```

```text
删除 → 重新 ffmpeg 解码。
```

## 6. 曲库索引

```text
data/cache/library_index.json
```

```text
键：文件路径
校验：size + mtime
版本：_v = 源码 hash
```

```text
只缓存可重建信息：uid / 标题 / 歌手 / 大小 / mtime 等。
不存 idx、播放状态、歌词。
删除 → 重新扫描/指纹。
```

## 7. 指纹索引

```text
data/cache/fingerprints.json
```

```text
只缓存路径 → (size, mtime, fp)。
算法、失效、读失败回退见 fingerprint.md。
```

## 8. 昂贵缓存：人声

```text
data/vocals/<uid>/
```

```text
可重建，但需要重新 demucs，不是普通 cache。
布局、纯音乐、LRU、清理见 vocals-jobs.md。
```

## 9. 临时文件

```text
data/tmp/vocals/<uid>-<pid>-<ms>/
```

```text
任务 finally 删除。
启动清理孤儿目录。
```

```text
可随时删。
```

## 10. 写入与并发

```text
缓存文件用 fsio.atomic_write。
缓存读取失败 = miss，不阻断主流程。
缓存写入失败不应伪装成权威写入成功。
```

```text
lyrics / annotations / wave 是单文件缓存。
library_index / fingerprints 是进程内聚合，flush 时原子写。
```

```text
缓存之间没有事务关系。
删除缓存不影响权威数据。
```

## 11. 清理命令

```text
make clean-cache
  → data/cache/lyrics
  → data/cache/wave
  → data/cache/annotations
  → 保留 app.log

make clean-index
  → data/cache/library_index.json
  → data/cache/fingerprints.json

make clean-vocals
  → data/vocals
  → data/tmp/vocals

make clean-tmp
  → data/tmp
```

```text
clean-cache 不清理索引/指纹，避免启动突然变慢。
需要清索引时用 clean-index。
```

## 12. 版本与失效规则

| 项 | 规则 |
|---|---|
| annotation `VERSION` | 自动取引擎/词典/渲染源码 hash |
| library_index `_v` | 自动取索引源码 hash |
| fingerprint `_v` | 自动取指纹源码 hash |
| wave `rate/step` | 自动进缓存路径 |
| wave `size/mtime` | 自动进缓存内容并校验 |
| lyrics cache | 无版本，按标题/歌手；force/re-match 更新 |

```text
不要用“删全部 cache”代替版本设计。
```

## 13. 负缓存

```text
歌词缓存可以保存 {miss:true, reason}
```

```text
命中未过期负缓存 → 不自动联网。
默认 7 天后过期；过期后自动重试。
也可用 re-match / force 立即重试。
```

```text
这是行为选择，不是 bug。
```

## 14. 已知问题

```text
1. clean-cache 和 clean-index 分开，用户需要知道区别。
2. 缓存写入失败有的地方静默，有的地方可能冒泡。
```

```text
waveform 的 size/mtime 失效已经补齐。
```

## 15. 不做

```text
不做缓存迁移。
不做多版本缓存共存。
不做跨设备同步。
不把缓存当权威数据。
```

## 16. 相关专题

```text
nhlrc 格式 → nhlrc.md
翻译来源/配对 → lyrics-matching.md
翻译列编辑 → lrc-editor.md
播放器状态 → player-state.md
指纹索引 → fingerprint.md
人声缓存 → vocals-jobs.md
曲库索引 → library.md
```
