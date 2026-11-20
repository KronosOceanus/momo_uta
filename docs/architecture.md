# 架构

> 读者：要加功能、改数据流、判断"这段代码该放哪"的人。
> 定位：分层、目录、边界规则、一次请求怎么走。
> 自成一体：不依赖其它文档；具体的格式/算法细节由各模块文档展开。

## 0. 三十秒版本

```text
桌面应用 = pywebview 窗口 + 本机 HTTP 服务

请求方向：
  前端（window.NH） → HTTP（routes） → service（编排） → core（数据/规则）
                                                        ↘ nihonco_yomi（纯计算）

依赖只能向下，不能反向。
scripts/check_arch.py 用 AST 检查，`make test` 会跑。
```

```text
五个包：
  nihonco_yomi        纯计算：注音、罗马音、词表、不变式
  nihonco_player.core 数据与规则：曲库、歌词、指纹、歌单、人声、波形
  nihonco_player.service 编排：单曲、LRC、歌单
  nihonco_player.http 协议：路由、静态文件、音频流
  nihonco_player_app  桌面壳：起服务、开窗口、文件对话框
```

## 1. 目标与边界

```text
是什么：
  · 本地优先的日语歌词练习播放器
  · 一个进程、一个窗口、一个本机端口
  · 数据在 data/；歌词标注是用户资产

不是什么：
  · 不是多用户服务（没有登录、没有数据库、没有远程 API 暴露）
  · 不是前端框架项目（没有打包器，四个 classic script）
  · 不是流式音频服务（整首解码进内存）
```

```text
三条设计约束：
① 纯计算与 IO 分开
   引擎不知道文件、网络、HTTP；core 不知道 HTTP；service 不知道窗口
② 数据有单一归属
   曲库/歌词/歌单/人声/波形各自有明确的读写模块
③ 前端只有一个全局
   window.NH；四个脚本按顺序加载，共享这个命名空间
```

## 2. 分层与依赖规则

```text
┌──────────────────────────────┐
│ nihonco_player_app（桌面壳）  │  webview、文件对话框、日志
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.http           │  路由、静态文件、Range
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.service        │  song / lrc / playlist
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_player.core           │  数据、文件、网络、缓存
└──────────────┬───────────────┘
               │ 调用
┌──────────────▼───────────────┐
│ nihonco_yomi                  │  纯计算，无 IO
└──────────────────────────────┘
```

```text
硬规则（check_arch.py）：
  1. nihonco_yomi 不能 import 任何 nihonco_player*
  2. core 不能 import service / http
  3. service 不能 import http
  4. http 不能 import nihonco_player_app
```

```text
违反时：make test 直接失败，输出"哪一行 import 了谁"。
目的不是洁癖，而是保证：
  · 引擎可以单独跑评测/命令行
  · core 可以在没有服务端的情况下被测试
  · service 可以被脚本直接调用
```

## 3. 目录

```text
src/
├── nihonco_yomi/               纯计算
│   ├── annotate.py             分词 → 片段 → 档位
│   ├── kana.py                 假名/汉字判定
│   ├── romaji.py               罗马音
│   ├── render.py               键位/展示
│   ├── invariants.py           I1–I8 不变式
│   ├── counters.py             覆盖率/档位统计
│   ├── llm.py                  LLM 辅助（可选）
│   ├── thresholds.py           设计阈值（A 类）
│   ├── config.py              运行参数（B 类）
│   ├── paths.py                路径常量
│   ├── common.py               共享小工具
│   └── serve.py                引擎命令行
│
├── nihonco_player/
│   ├── core/                   数据与规则
│   │   ├── library.py          扫库、CACHE、refresh、标签
│   │   ├── lyrics.py           歌词门面（fetch/cache/text 的聚合）
│   │   ├── lyrics_fetch.py     网易云 / MB / lrclib
│   │   ├── lyrics_text.py      名称/语言/打分/排除
│   │   ├── lyrics_cache.py     歌词缓存读写
│   │   ├── lrc_doc.py          LRC/nhlrc 格式（纯函数）
│   │   ├── lrc_files.py        data/lyrics 读写、备份
│   │   ├── annotation.py       行 → seg、对齐、渲染
│   │   ├── fingerprint.py      音频指纹 + 索引
│   │   ├── song_meta.py        整体偏移/标签元数据
│   │   ├── playlists.py        歌单文件
│   │   ├── importing.py        导入配对
│   │   ├── vocals.py           demucs 队列 + VAD
│   │   ├── waveform.py         峰值
│   │   └── diag.py             诊断日志
│   │
│   ├── service/                编排
│   │   ├── song.py             载荷、改读音、匹配、选候选
│   │   ├── lrc.py              编辑模式读写、导入导出、备份
│   │   └── playlist.py         歌单增删改、导入、打标
│   │
│   ├── http/
│   │   ├── routes.py           路由与参数校验
│   │   ├── server.py           ThreadingHTTPServer
│   │   └── static.py           静态文件 + Range
│   │
│   ├── static/                 前端（无构建）
│   │   ├── player.html
│   │   ├── player.css
│   │   ├── 05-audio.js         音频引擎
│   │   ├── 10-app.js           状态/载入/波形/人声/提示
│   │   ├── 20-editor.js        LRC 打轴
│   │   └── 30-playback.js      时间语义/播放条/高亮
│   │
│   └── web.py                  页面装配 + 注入 __CFG
│
├── nihonco_player_app/         桌面壳
│   ├── __main__.py             起服务、开窗口、文件对话框
│   └── logsetup.py             日志文件/异常钩子
│
config/defaults.json            仓库默认运行参数
data/                           运行数据（见 §10）
docs/                           文档
scripts/check_arch.py           分层检查
scripts/check_js.py             前端完整性检查
tests/                          Python + Node 测试
tools/                          建表/评测/演示
```

## 4. 引擎层 `nihonco_yomi`

```text
输入：日文歌词行（字符串）
输出：片段序列 [{base, ruby, level}]、罗马音、键位、覆盖率

不碰：
  · 文件系统（除了 paths 常量）
  · 网络
  · 曲库/歌单/HTTP

所以它可以：
  · 在命令行单独跑（serve.py）
  · 在评测里批量跑（eval/）
  · 在 core 里被 annotation.py 调用
```

```text
两类参数要分清：

A 类：设计阈值
  位置：nihonco_yomi/thresholds.py
  例子：MIN_CORPUS_N、SINGLE_READING_SHARE、语料统计下限
  含义：决定 A/AB/B 的切法
  改了必须重跑 make stats 和三套评测

B 类：运行参数
  位置：config/defaults.json + data/config.json
  例子：时长差、波形采样率、人声阈值、窗口尺寸
  含义：不改判定规则，只调行为
  改了重启（或刷新页面）生效

paths.py 只放路径常量，不放逻辑。
```

## 5. `core`：数据与规则

### 5.1 模块分组

```text
曲库
  library.py      扫目录、条目、CACHE、标签
  fingerprint.py  音频身份（uid）
  song_meta.py    整体偏移、展示用元数据

歌词来源
  lyrics.py       门面：fetch + cache + text 的聚合
  lyrics_fetch.py 网易云 / MusicBrainz / lrclib
  lyrics_text.py  名称归一、语言、打分、排除
  lyrics_cache.py 缓存文件

歌词文件
  lrc_doc.py      纯格式：解析/渲染/校验/对齐
  lrc_files.py    data/lyrics 路径、读写、备份
  annotation.py   行文本 → seg（调用引擎）

播放器数据
  playlists.py    歌单 JSON
  importing.py    文件配对
  vocals.py       人声分离队列
  waveform.py     波形峰值
  diag.py         诊断日志
```

```text
core 的特点：
  · 可以直接被脚本/测试调用，不需要 HTTP
  · 不返回 HTML；只返回数据/路径/状态
  · 文件写入集中在少数模块（lrc_files / playlists / cache / meta）
```

### 5.2 曲库与 `CACHE`

```text
CACHE：idx(str) → 条目
  条目字段：
    key       md5(文件名主干)[:12]        用于标签/偏移等"按歌"的元数据
    uid       音频指纹                    用于歌词/歌单/人声
    file      绝对路径
    stem      文件名主干
    title/artist/orig
    has_lyric 是否有可用歌词
    source/lang/suspect
    group     所在目录

idx 是"当前会话里的位置"：
  每次全量扫库都可能变；不能持久化，不能当身份。
```

```text
refresh(uid)：
  uid 在 CACHE 里 → 只重算这一条（不扫全库、序号不变）
  uid 不在 → 全量扫描并重建 CACHE

scan_library()：
  按 music_dirs 递归；扩展名来自 library.extensions
  + data/curated/imports.json 里登记的导入文件
  用指纹索引避免每次重算
```

### 5.3 三个 id 不要混

```text
idx    会话内位置：/api/song/<idx>、/audio/<idx>
uid    音频指纹：歌词文件、歌单成员、人声缓存
key    md5(文件名主干)：标签、整体偏移等按歌元数据
```

```text
一个常见错误：把 idx 写进歌单。
idx 每次启动都可能变；歌单只存 uid。
```

## 6. `service`：编排

```text
service 只做"把 core 的步骤串起来"，不实现具体规则：
  · 读哪个文件、调用哪个 core 函数、按什么顺序
  · 返回前端要的载荷/结果
  · 不解析 HTTP，不碰窗口
```

### 6.1 song

```text
song_payload(idx)
  曲库条目 → 歌词（data/lyrics 或缓存）→ 逐行注音 → 必要时自动落盘
  → {idx, title, artist, lines, offset, audio, pending?}

edit_line_action(req)
  改一处读音 → 重算该行 → 立即写 nhlrc → 返回新 ruby/rm/ky

rematch(idx, duration)
  候选只来自网络（网易云）→ 返回前 10

pick(idx, id)
  网络歌词重写当前 nhlrc 正文（备份、读音重来）

lazy_match(item)
  强制联网取歌词 → 写缓存 → 刷新曲库
```

### 6.2 lrc

```text
lrc_action(req)：
  load      读当前歌词（rows + metadata）
  save      对齐旧读音、重新注音、写 nhlrc
  backup    查 .bak 是否存在/时间/行数
  restore   用 .bak 覆盖
  export    生成 nhlrc 与纯 lrc 两种文本
  import_lrc 导入文本（保留 nhlrc 读音）
```

### 6.3 playlist

```text
playlists_action(req)：
  list_create / list_rename / list_delete / list_clear
  entry_remove / entry_move / entries_move / entry_reorder / list_reorder
  ui_open / ui_offset
  match（懒匹配）
  edit_clear（清空标注，恢复默认）
  import（导入音频/歌词，走 import_to_list）

```

```text
所有 action 都是"一个 req dict 进、一个 dict 出"，
方便 HTTP 和脚本共用。
```

## 7. `http`：协议层

```text
routes.py 只做三件事：
  ① 解析路径/JSON
  ② 校验必填字段（缺失 400）
  ③ 转发给 service，JSON 返回
```

### 7.1 路由

```text
GET
  /                       页面（注入 __CFG）
  /static/*               前端静态文件
  /api/song/<idx>         单曲载荷
  /api/pl、/api/playlists  歌单列表
  /api/library            曲库列表
  /api/wave/<idx>[?src=vocals]  波形峰值
  /api/vocals/<idx>       人声状态
  /audio/<idx>            音频流（Range）

POST
  /api/pl                 playlists_action
  /api/playlist           同上（别名）
  /api/line               改一处读音
  /api/rematch            重新匹配候选
  /api/pick               选中候选
  /api/import/one         导入
  /api/lrc                LRC 编辑模式
  /api/vocals             人声分离 ensure
```

```text
必填字段在 REQUIRED 表里声明：
  缺了直接 400，返回 {"ok":false,"error":"缺少参数：…"}
  不让 service 里出现 KeyError/None 兜底
```

### 7.2 音频与静态

```text
/audio/<idx>：
  支持 Range（206），按 64KB 分块写
  Content-Type 按扩展名映射
  前端 WebAudio 需要整文件 fetch，但 Range 仍保留给浏览器/调试

/static/*：
  只读、防目录穿越、文本按 UTF-8
```

### 7.3 错误约定

```text
HTTP 层：
  400  参数缺失 / 非法 JSON
  404  未知路径 / 未知歌曲 / 音频文件不存在
  200  正常；业务失败用 {"ok":false,"error":"…"} 表达

service 层：
  不抛业务异常给前端；返回 {ok/error} 或 {error}
```

## 8. 桌面壳 `nihonco_player_app`

```text
启动顺序：
  ① logsetup.setup()：日志文件 + sys.excepthook
  ② scan_library() → 填 CACHE
  ③ make_server(0)：随机端口，只绑 127.0.0.1
  ④ 后台线程 serve_forever
  ⑤ webview.create_window + start
```

```text
窗口里的前端通过 window.pywebview.api 调本机能力：
  pick_any()       一个对话框选文件/文件夹/多个
  pick_folder()    兼容旧接口
  save_text(name, nhlrc, lrc)  导出；.lrc 扩展名写纯 LRC
  pick_lrc_text()  选歌词文件并读文本
```

```text
为什么用随机端口：
  避免固定端口冲突；服务只在本机回环地址。
```

## 9. 前端

```text
没有构建步骤：
  player.html 按顺序加载四个 classic script
  每个脚本是一个 IIFE，只通过 window.NH 暴露
  check_js.py 会检查：
    · 每个文件语法
    · 四个文件拼起来语法（抓跨文件重复定义）
    · 必须是 IIFE
    · 必须取 window.NH
```

```text
分工：
  05-audio.js    AudioEngine：解码、播放、seek、变速、音量
  10-app.js      状态、曲库/歌单、载入、波形、人声、toast
  20-editor.js   LRC 表格、打轴、保存、导入导出
  30-playback.js 时间语义、播放条、高亮、循环、键盘

共享状态都在 NH 上：
  NH.S / NH.LINES / NH.WAVE / NH.VIEW / NH.LRCEDIT …
```

```text
配置注入：
  web.page() 把 config 整个塞进 window.__CFG
  前端只读，不在前端写配置
```

```text
DOM 约定：
  左栏 .ln、右栏 .ln2、编辑表格 .lerow
  状态用 class（.on/.sel/.picked/.dirty）而不是内联样式
```

## 10. 数据布局

```text
data/
├── lyrics/            歌词标注（nhlrc）        进 git（用户资产）
├── vocals/            人声分离结果             不进 git（可重算但贵）
├── cache/             可重建缓存               不进 git
│   ├── lyrics/        歌词抓取缓存
│   ├── wave/          波形峰值
│   ├── fingerprints.json 路径→指纹索引
│   └── app.log
├── curated/           人工/运行维护的数据       进 git
│   ├── playlists.json、song_meta.json
│   ├── imports.json（导入的音频路径）
│   ├── lyrics_exclude.json、counters.json、glossary_lyrics.json
│   └── *.lock         文件锁                   不进 git
├── config.json        本机配置覆盖             不进 git
├── sources/           原始下载                 不进 git
├── corpus/            语料统计                 不进 git
└── tables/            词典机械抽取             不进 git
```

```text
归属原则：
  · 用户资产（歌词/歌单/标签/偏移）→ 进 git，备份有意义
  · 可重建（缓存/波形/人声/语料）→ 不进 git，删了能重算
  · 原始素材（sources）→ 不进 git，体积大
```

## 11. 配置

```text
config/defaults.json   仓库默认值（六组）
data/config.json       本机覆盖（同结构，深层合并）
window.__CFG           注入前端

六组：
  lyrics    匹配与打分
  player    播放器通用 + ui
  waveform  波形
  vocals    人声分离
  library   扫描/导入
  app       桌面壳/日志
```

```text
优先级：代码里的 _FALLBACK < defaults.json < data/config.json
改 B 类参数：重启（后端）或刷新（纯前端 ui）生效。
A 类阈值不走这里（见 §4）。
```

## 12. 并发与一致性

```text
后端：
  library._LOCK        refresh/扫库串行（RLock）
  lrc_files.LOCK       同一首歌的读-改-写串行（RLock）
  vocals._queue        单线程队列，分离任务串行
  HTTP                ThreadingHTTPServer，每个请求一个线程

前端：
  SAVE_PENDING         同一时刻最多一个保存请求
  LOAD_REQUEST         切歌/载入的旧响应自动作废
  LRC_OPEN_REQUEST     多次进入编辑模式只认最后一次
  SEEK_SEQ             连续跳转只执行最后一次
```

```text
一致性策略：
  · 歌词以 data/lyrics 的文件为唯一真相
  · 自动落盘失败只记日志，不阻塞播放
  · 保存失败保留 dirty，不假报成功
```

## 13. 新功能放哪

```text
纯文本→读音/罗马音/档位              nihonco_yomi
读写某个数据文件、调外部命令           core
串多个步骤、组装前端载荷               service
新增 URL/参数校验                     http
窗口/文件对话框/日志                   nihonco_player_app
交互/渲染/播放                          static/*.js
```

```text
判断标准：
  · 需要 HTTP 吗？需要 → http
  · 需要窗口吗？需要 → app
  · 需要多处复用、涉及文件/网络吗？需要 → core
  · 只是编排？→ service
  · 纯计算？→ yomi
```

## 14. 测试与校验

```text
make test =
  scripts/check_arch.py   分层边界
  scripts/check_js.py     前端完整性
  Python unittest         145 条
  node --test             前端逻辑 9 条
```

```text
测试的组织：
  tests/test_lrc_doc / nhlrc / lyrics_store   格式与存储
  tests/test_importing / fingerprint          导入与身份
  tests/test_player_http / playlists_api      接口层
  tests/test_rematch                          匹配
  tests/test_ui_smoke                         真窗口冒烟
  tests/lrc_editor.test.cjs                   前端时间/保存/锁定
```

## 15. 已知取舍

```text
① 单进程、无数据库
   好处：部署简单、数据可 diff；代价：并发能力有限

② 前端无构建
   好处：改完刷新即可；代价：没有类型检查/模块系统，
   只能靠 check_js 和 NH 约定维持

③ 整首音频解码
   好处：seek 采样级精确；代价：内存与首播等待

④ idx 会变
   所有持久化只能用 uid/key，不能用 idx

⑤ 文件即真相
   data/lyrics 与 data/curated 是唯一状态；没有隐藏内存数据库
   好处：可备份/可手改；代价：需要文件锁与串行化
```
