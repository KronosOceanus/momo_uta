# 架构与边界

> 当前代码快照。读者：要加功能、改数据流、判断“这段代码该放哪”的维护者。
> 本文只写边界和流程；字段格式、翻译规则、播放器状态机放专题文档。

## 0. 三十秒版本

```text
桌面应用 = pywebview 窗口 + 本机 HTTP 服务

依赖向下：
  app → http → service → core → yomi

请求：
  NH → HTTP → service → core / yomi → data/

三条硬约束：
  1. 数据有唯一归属
  2. 异步结果必须能判断归属
  3. 权威文件和可重建缓存不能混写
```

## 1. 分层与依赖规则

### 1.1 依赖图

```text
momo_uta_app        桌面壳：起服务、开窗口、文件对话框、全局热键
        │
        ▼
momo_player.http       路由、静态文件、Range、页面装配
        │
        ▼
momo_player.service    单曲、歌词、歌单、任务、主题的编排
        │
        ▼
momo_player.core       数据、文件、缓存、网络、进程
        │
        ▼
momo_yomi              注音计算与运行时资源
```

```text
允许向下跨层，不允许反向。
```

`scripts/check_arch.py` 实际检查的禁止前缀：

```text
momo_yomi       × momo_player* / momo_uta_app
core               × service / http / app
service            × http / app
http               × app
```

检查器只做 Python 静态 import 前缀检查：

```text
· 不检查运行时动态 import
· 不检查行为
· 不检查前端
```

团队约定比检查器更细：

```text
HTTP 直接 import core 是允许的；
routes 中确实有 library / diag 这类只读辅助引用。
默认仍优先 service，直接引用 core 只用于协议层辅助。
```

### 1.2 请求链

```text
前端 window.NH
  → /api/*
  → http.routes
  → service.*
  → core.*
  → momo_yomi 或 data/
```

`momo_uta_app` 不参与请求链。它只负责启动 HTTP 服务、创建窗口、提供本地文件对话框和系统级热键。

### 1.3 yomi 的定位

准确说法：

```text
注音引擎与运行时资源
```

不是严格的无 IO 纯函数包：

```text
config.py     读 config/defaults.json + data/config.json
paths.py      路径常量
annotate.py   延迟加载 Sudachi 词典
llm.py        可选的 LLM 网络调用
```

计算核心仍然是：

```text
annotate / romaji / render / kana / counters / invariants / thresholds
```

## 2. 数据归属

### 2.1 数据根目录

```text
开发：
  <repo>/data

打包：
  ~/Library/Application Support/momo uta/data
  可用 MOMO_HOME 覆盖
```

```text
本文表格里的 data/... 都相对于这个根目录。
只读表/静态文件在 .app 的 Resources，不在用户数据根。
```

### 2.2 权威数据

| 数据 | 身份键 | 写入者 | 删除后的行为 |
|---|---|---|---|
| `data/lyrics/*.nhlrc` | uid | `lrc_files`（经 service） | 写 disabled 文档，仍是用户选择 |
| `data/curated/playlists.json` | list id | `playlists` | 默认歌单仍存在 |
| `data/curated/song_meta.json` | uid | `song_meta` | offset 回到 0 |
| `data/curated/imports.json` | 音频路径 | `library` | 导入历史丢失 |
| `data/config.json` | 配置路径 | `user_config` | 回到 `config/defaults.json` |

### 2.3 可重建缓存

| 数据 | 身份键 | 写入者 | 删除后的行为 |
|---|---|---|---|
| `data/cache/lyrics/*.json` | 标题 + 歌手 | `lyrics_fetch` | 重新联网匹配 |
| `data/cache/annotations/*.json` | 版本 + 行文本 + stored | `annotation_cache` | 重新注音 |
| `data/cache/wave/*.json` | 音频 + source + 参数 | `waveform` | 重新算峰值 |
| `data/cache/library_index.json` | 文件路径 | `library_index` | 重新扫库 |
| `data/cache/fingerprints.json` | 文件路径 | `fingerprint` | 重新算指纹 |
| `data/vocals/<uid>/` | uid | `vocals` | 重新分离（很贵） |

```text
data/cache 可随时删。
data/vocals 可重建，但成本高。
data/tables、data/sources、data/corpus、eval/ 是仓库/评测数据，不是播放器运行数据。
```

### 2.4 `.nhlrc` 内部

```text
正文       rows 顺序，权威
rows       lyric / blank / metadata
lines      读音，i(body) + lid + h + seg + tid
trans      翻译，i(body) + lid + h + text
trans_lang 翻译语言，缺省 zh
disabled   持久化的“用户删除了这首歌的歌词”
```

```text
i 是 body 行号，只负责锚定
lid 是行身份
tid 是 token 身份
blank / metadata 不进入 lines / trans
```

```text
正文、读音、翻译都属于权威歌词文档。
disabled 也是持久化用户选择，不是缓存。
```

### 2.5 身份

```text
uid   歌曲身份，也是 offset 的键
row.id 编辑器行身份
lid   歌词行身份，跨插入/删除/移动保持
tid   歌词 token 身份
idx   曲库展示位置，不是身份
key   历史字段，不再作为 offset / 身份
h     行正文变更检测，不是身份
i     正文锚点，不是身份
```

```text
lid/tid 只解决歌词编辑内部的身份；
它们不参与歌曲查找，也不进入 url。
```

### 2.6 歌词缓存与翻译

```text
data/cache/lyrics 里的 tlyric 只是抓取结果。
没有 .nhlrc 时，tlyric 可用于显示。
pick / 保存后，翻译才进入权威文档的 trans。
有 .nhlrc 但没有 trans 时，不自动回填缓存翻译。
```

### 2.7 歌词解析与保存链

```text
core.lyric_rows.parse_rows()
  → rows:
      lyric / blank / metadata
  → playable()
      lyric && t != null
      按时间排序，同时间按文档顺序

service.lyric_document
  → load_rows / save_rows
  → rows 直接读写

service.song.save_lyrics()
  → 旧兼容入口：body 入参 → rows
  → LRC.save() 写 v2
```

```text
新代码只有一套行模型：rows。
不再维护 body_rows / compact 两套权威行号。
```

## 3. 模块地图

### momo_yomi

```text
annotate       分词 → 片段 → 档位 → 整行注音
romaji         罗马音 / IME 键位
render         片段 → HTML
kana           假名判定
counters       数词读音
invariants     不变式
thresholds     设计阈值
config         运行参数
paths          路径常量
llm            可选 LLM 消歧
```

### core

```text
曲库     library / library_index / fingerprint
歌词     lyrics / lyrics_fetch / lyrics_text / lyrics_cache
格式     lyric_rows（v2 rows）/ lrc_doc（旧解析）/ lrc_files（权威写入）
注音     annotation / annotation_cache
歌单     playlists
属性     song_meta
导入     importing
任务     jobs / vocals
其它     waveform / fsio / diag / user_config
```

### service

```text
song       载荷、旧保存兼容、改读音、匹配、pick
lyric_document  v2 rows 读写、播放派生、按 lid 改读音
lrc        编辑、导入导出、备份、v2/旧 API
playlist   歌单动作、导入、ui_offset
jobs       任务编排
settings   主题校验与持久化编排
```

### http

```text
routes     路由、参数校验、JSON 结果
server     ThreadingHTTPServer
static     静态文件与 Range
web        页面装配 + __CFG + data-theme
```

### app

```text
__main__   起服务、开窗口、文件对话框、关闭隐藏
logsetup   日志与异常钩子
hotkeys    macOS 全局快捷键
```

### static

```text
05-audio       AudioEngine
06-state       查看歌曲状态机
10-app         状态、加载、波形、toast、主题
11-vocals      人声任务
12-library     歌单、多选、拖拽、导入
20-editor      LRC 编辑 + picker
30-playback    时间语义、播放条、高亮、循环
40-shortcuts   应用内快捷键分发
```

## 4. 请求与数据流

### 4.1 GET `/api/song/<uid>`

```text
NH.load
  → GET /api/song/<uid>
  → service.song.song_payload
  → service.lyric_document.load_rows
      v2：rows
      V1：不再读取
      无 nhlrc：歌词缓存/旧路径
  → core.lyric_rows.playable
      按时间排序，同时间按文档顺序
  → core.annotation_cache.line_fields（逐行）
      命中：直接返回
      未命中：调用 yomi 引擎，再写缓存
  → payload lines：ruby / rm / ky / rmH / kyH / trans
```

```text
disabled 分支：直接返回空歌词，不注音、不联网。
```

### 4.2 POST `/api/rematch`

```text
rematch
  → 搜索候选
  → 读取当前歌词（get_lrc，可能触发当前歌自动匹配并写歌词缓存）
  → 不抓列表里候选的正文
  → 不写 nhlrc
```

```text
候选正文只在用户 pick 时抓取。
lazy_match 也会抓当前歌正文并写缓存。
```


### 4.3 POST `/api/pick`

```text
pick
  → fetch_lyrics_by_id
  → 一次显式返回 {lrc, tlyric}
  → tlyric 按时间/行序配对原文
  → save_lyrics(mode="replace")
  → 重写 v2 nhlrc
```

```text
旧读音不保留。
旧翻译不保留。
新翻译随候选正文一起写入。
```

### 4.4 LRC 保存

```text
POST /api/lrc {action:save_rows, rows, version}
  → service.lyric_document.save_rows
  → lrc_files.save_rows（版本校验 + 备份 + 原子替换）

旧 lines 入口：
  → service.song.save_lyrics
  → 内部转 rows
  → lrc_files.save 写 v2
```

```text
lines 里每行可带 trans。
trans 不进入正文，只进入 nhlrc 尾部。
```

### 4.5 offset / 本机配置

```text
ui_offset
  → service.playlist
  → song_meta.put(uid, offset)

song_payload
  → song_meta.get(uid, offset)

POST /api/theme
  → service.settings
  → core.user_config
  → data/config.json
```

### 4.6 人声任务

```text
POST /api/jobs
  → service.jobs
  → core.jobs（job 生命周期）
  → core.vocals（队列、进程、分离）
```

```text
job.state 是任务生命周期。
job.stage 是人声执行阶段。
job 已经 running，VOC 仍可能是 queued。
```

## 5. 写入、并发与版本

| 保护 | 解决的问题 |
|---|---|
| `fsio.atomic_write` | 单文件替换不出现半写 |
| `fsio.locked` + `LRC.LOCK` | 歌词读改写线程/进程串行 |
| `expected_version` | 拒绝过期草稿 |
| `SAVE_PENDING` | 当前会话的保存串行 |
| `LRC_REPLACING` | 替换/删除期间禁止切歌 |
| `NH.track(domain)` | 旧异步响应不能改当前状态 |
| `AudioEngine._loadSeq` | 旧 fetch/decode 不能写当前 buffer |

必须区分：

```text
token        请求归属（load / wave / lrcOpen / seek）
SAVE_PENDING 保存队列
LRC_REPLACING 排他锁
```

```text
AudioEngine._loadSeq 保留实例内序号，不提升为全局。
```

## 6. 前端状态

### 6.1 例子：查看 B，播放 A

```text
NH.S = B           当前查看
NH.PLAYING_UID = A 当前播放
```

```text
切换播放源不等于切换查看页面。
句级操作可能把页面带回 A。
```

### 6.2 例子：关闭翻译列后保存

```text
NH.TRANS_EDIT = false
EROWS[i].trans 仍然存在
lrcPayload() 仍然携带 trans
保存不会清空翻译
```

### 6.3 变量表

| 变量 | 归属 |
|---|---|
| `NH.S` | 当前查看歌曲 |
| `NH.PLAYING_UID` | 当前播放歌曲 |
| `NH.VIEW_MODE` | `normal` / `lrc` / `kana` |
| `NH.LINES` | 普通页歌词 |
| `NH.EROWS` | LRC 编辑行（含 trans） |
| `NH.LRC_VERSION` | 文档版本 |
| `NH.SELU` | 歌单多选 |
| `NH.loop` / `NH.LOOP_ROW` | 单句循环 |
| `NH.TRANS_EDIT` | 翻译列开关，不是数据 |
| `NH.REQ` | 请求 domain 序号 |
| `NH.SAVE_PENDING` | 保存队列 |
| `NH.LRC_REPLACING` | 替换排他锁 |

### 6.4 快捷键

```text
应用内：40-shortcuts.js
全局：momo_uta_app/hotkeys.py（⌃⌥←/→/P）
```

```text
输入框、按钮、对话框、IME 组词中不抢键。
```

## 7. 检查与测试

```text
改分层 / import
  → make arch

改 nhlrc / 翻译 / offset / 数据归属
  → Python 领域测试

改切歌 / 保存 / 音频时序
  → 前端 VM 测试

跨层交付
  → make test
```

检查器能力：

```text
check_arch.py
  Python 静态 import 前缀
  不查动态 import / 行为 / 前端

check_js.py
  语法
  IIFE / window.NH 命名空间
  多文件拼接后的重复定义
  不查运行时行为
```

## 8. 专题文档

本文只保留边界。字段、流程和实现细节看各专题：

```text
歌词数据模型.md          单一行模型设计
topics/nhlrc.md            歌词文件格式
topics/nhlrc-token-ids.md  行/token 身份升级
topics/cache.md            缓存/持久化
topics/fingerprint.md      音频指纹与 uid
topics/lyrics-matching.md  歌词搜索/过滤/配对
topics/player-state.md     查看/播放/编辑状态
topics/lrc-editor.md       LRC 编辑与保存
topics/audio.md            WebAudio 播放
topics/vocals-jobs.md      人声任务与 job
topics/library.md          曲库/歌单/导入
topics/http-api.md         本机 HTTP API
topics/development.md      开发/测试/检查器
topics/packaging.md        打包
```

> 旧架构文档已移到 `docs/history2/`，不作为当前基线。
